import re
import urllib.parse

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from util.profile_folder_protocols import BrowserProfileProtocol


# The "?t" query is at the start to omit some other hits which can be misleading (partially written search terms
#  for example. Need to confirm that this doesn't omit something useful/there are other ways to start this query.
SEARCH_URL_PATTERN = re.compile(r"https?://.*duckduckgo.*?\.[A-z]{2,3}/\?t.*q=")
SEARCH_LINK_URL_PATTERN = re.compile(r"https?://links.duckduckgo.*?\.[A-z]{2,3}/d.js")


def _get_search_details(url: str):
    url = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(url.query)
    search_term = query.get("q", [None])[0]

    return search_term


def ddg_search_urls(
        profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    for history_rec in profile.iterate_history_records(url=SEARCH_URL_PATTERN):
        search_term = _get_search_details(history_rec.url)
        results.append(
            {
                "timestamp": history_rec.visit_time,
                "search term": search_term,
                "original url": history_rec.url,
                "source": "history",
                "location": history_rec.record_location,
            }
        )

    for cache_rec in profile.iterate_cache(
            url=lambda u: (SEARCH_LINK_URL_PATTERN.search(u) or SEARCH_URL_PATTERN.search(u)) is not None):
        search_term = _get_search_details(cache_rec.key.url)
        results.append(
            {
                "timestamp": cache_rec.metadata.request_time if cache_rec.metadata is not None else None,
                "search term": search_term,
                "original url": cache_rec.key.url,
                "source": "cache",
                "location": str(cache_rec.metadata_location)
            }
        )

    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "Duckduckgo",
        "Duckduckgo searches",
        "Recovers Duckduckgo searches from URLs in history, cache",
        "0.2",
        ddg_search_urls,
        ReportPresentation.table
    ),
)