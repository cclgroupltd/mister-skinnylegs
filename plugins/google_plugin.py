import base64
import json
import re
import datetime
import struct
import urllib.parse

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from ccl_chromium_reader import ChromiumProfileFolder
from util.profile_folder_protocols import BrowserProfileProtocol


EPOCH = datetime.datetime(1970, 1, 1)
SEARCH_URL_PATTERN = re.compile(r"https?://.*google.*?\.[A-z]{2,3}/search")


def parse_unix_seconds(secs):
    return EPOCH + datetime.timedelta(seconds=secs)


def parse_unix_ms(ms):
    return EPOCH + datetime.timedelta(milliseconds=ms)


def _get_search_details(raw_url):
    url = urllib.parse.urlsplit(raw_url)
    query = urllib.parse.parse_qs(url.query)
    search_term = query.get("q", [None])[0]

    if search_term is None:
        return None

    ei_timestamp = None
    ei_b64 = query.get("ei", [None])[0]

    if ei_b64:
        b64_padding = 4 - (len(ei_b64) % 4)
        ei_b64 += ("=" * b64_padding)
        ei = base64.urlsafe_b64decode(ei_b64)
        ei_timestamp = parse_unix_seconds(struct.unpack("<I", ei[0:4])[0])

    return {"search term": search_term,
            "ei session start timestamp": ei_timestamp}


def google_search_urls(
        profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    # TODO: this is extremely basic as a first pass POC - search URLs store so much more than the search-term

    results = []
    for history_rec in profile.iterate_history_records(url=SEARCH_URL_PATTERN):
        search_details = _get_search_details(history_rec.url)
        if search_details is None:
            continue

        history_rec_details = {
            "source": "History",
            "location": history_rec.record_location,
            "domain": urllib.parse.urlparse(history_rec.url).hostname,
            "timestamp": history_rec.visit_time,
        }

        history_rec_details.update(search_details)
        results.append(history_rec_details)

    has_response_time = isinstance(profile, ChromiumProfileFolder)
    for cache_rec in profile.iterate_cache(url=SEARCH_URL_PATTERN, omit_cached_data=True):
        cache_url = cache_rec.key.url
        search_details = _get_search_details(cache_url)
        if search_details is None:
            continue

        cache_rec_details = {
            "source": "Cache URLs",
            "location": str(cache_rec.metadata_location),
            "domain": urllib.parse.urlparse(cache_url).hostname,
            "timestamp": cache_rec.metadata.request_time
        }

        cache_rec_details.update(search_details)
        results.append(cache_rec_details)

    for sess_rec in profile.iter_session_storage(host=re.compile(r"^https://www.google"), key=re.compile(r"^hsb;")):
        hsb_obj = json.loads(sess_rec.value.split("_", 1)[1])
        search_details = None
        if "url" in hsb_obj:
            search_details = _get_search_details(hsb_obj["url"])

        if search_details is None:
            continue

        hsb_timestamp = parse_unix_ms(int(sess_rec.key.split(";;", 1)[1]))

        sess_rec_details = {
            "source": "Session Storage",
            "location": sess_rec.record_location,
            "domain": urllib.parse.urlparse(sess_rec.host).hostname,
            "timestamp": hsb_timestamp,
        }

        sess_rec_details.update(search_details)

        results.append(sess_rec_details)

    results.sort(key=lambda x: x["timestamp"] or datetime.datetime(1601, 1, 1))
    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "Google",
        "Google searches",
        "Recovers google searches from URLs in history, session storage, cache",
        "0.4",
        google_search_urls,
        ReportPresentation.table
    ),
)

