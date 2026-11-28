import base64
import binascii
import json
import re
import datetime
import struct
import urllib.parse

from mister_skinnylegs.util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from mister_skinnylegs.util.profile_folder_protocols import BrowserProfileProtocol


EPOCH = datetime.datetime(1970, 1, 1)
SEARCH_URL_PATTERN = re.compile(r"https?://.*google.*?\.[A-z]{2,3}/search")

# Google AI Mode / encoded query URL parameters:
#   udm=50 identifies the AI Mode results vertical (other udm codes are other
#   verticals, e.g. udm=2 for images);
#   mq carries the AI Mode follow-up query;
#   gs_lp / gs_lcp are URL-safe base64-encoded protobuf blobs which embed the
#   query text (field 4) and the Google web search client (field 2, e.g.
#   "gws-wiz", "gws-wiz-serp");
#   sxsrf embeds a millisecond Unix timestamp after its final ":".
AI_MODE_UDM_CODE = "50"
ENCODED_QUERY_PARAMS = ("gs_lp", "gs_lcp")
ENCODED_QUERY_FIELD = 4
ENCODED_CLIENT_FIELD = 2

# Google session storage values include the search box ("hsb;") records and
# comma-separated rows beginning with a URL and (where present) a Unix
# microsecond timestamp in the following field, e.g.
#   https://www.google.com/search?...&q=...,1787847278737667,1,...
# (the same row shape appears in other tools' session/tab exports, e.g. Safari
# history exports converted from JSON to CSV - the timestamp and trailing
# fields belong to the export row, not the URL itself).
SESSION_SEARCH_URL_PATTERN = re.compile(r"https?://[^\s\"',;]+/search[^\s\"',;]*")
SESSION_MICROS_PATTERN = re.compile(r",\s*(\d{16})\b")

# Google Translate URLs:
#   translate.google.<tld>/?hl=..&sl=..&tl=..&text=..&op=translate - the web UI
#   translate.google.<tld>/translate?...&u=<url> - webpage translation requests
#   translate.google.<tld>/#sl/tl/text - the legacy pre-2017 hash-based format
#   translate.googleapis.com/translate_a/single|t|l?...&q=.. - the API calls
#     made by the UI (their cached responses embed the translated output and
#     the detected source language)
TRANSLATE_URL_PATTERN = re.compile(r"https?://translate\.google(?:apis)?\.[A-Za-z.]+/")
TRANSLATE_API_URL_PATTERN = re.compile(r"https?://translate\.googleapis\.com/translate_a/[a-z]+\?")
TRANSLATE_HASH_URL_PATTERN = re.compile(r"#(?P<sl>[^#/]+)/(?P<tl>[^#/]+)/(?P<text>.+)$")


def parse_unix_seconds(secs):
    return EPOCH + datetime.timedelta(seconds=secs)


def parse_unix_ms(ms):
    return EPOCH + datetime.timedelta(milliseconds=ms)


def _read_varint(data: bytes, pos: int):
    """
    Reads a single protobuf base-128 varint from data at pos. Returns
    (value, new_pos), or (None, None) if the varint is malformed/truncated.
    """
    result = 0
    shift = 0
    while True:
        if pos >= len(data) or shift > 63:
            return None, None
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def decode_base64_protobuf_strings(value: str) -> dict[int, list[str]]:
    """
    Decodes a URL-safe base64 encoded protobuf message (as used in the
    gs_lp/gs_lcp Google search URL parameters) and returns the string values
    of its length-delimited fields, keyed by field number. Fields which do not
    contain printable UTF-8 (e.g. nested messages, packed varints) are skipped.
    Truncated or non-base64 values return whatever fields could be parsed.
    """
    padded = value.strip() + "=" * (-len(value.strip()) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError):
        return {}

    fields: dict[int, list[str]] = {}
    pos = 0
    while 0 <= pos < len(raw):
        tag, pos = _read_varint(raw, pos)
        if tag is None:
            break
        field_number, wire_type = tag >> 3, tag & 0x7
        if wire_type == 2:  # length-delimited
            length, pos = _read_varint(raw, pos)
            if length is None or pos is None or pos + length > len(raw):
                break
            chunk = raw[pos:pos + length]
            pos += length
            try:
                text = chunk.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if all(character.isprintable() for character in text):
                fields.setdefault(field_number, []).append(text)
        elif wire_type == 0:  # varint
            _, pos = _read_varint(raw, pos)
        elif wire_type == 1:  # 64-bit
            pos += 8
        elif wire_type == 5:  # 32-bit
            pos += 4
        else:
            break  # unknown wire type; cannot continue safely
    return fields


def _get_ei_timestamp(query_params: dict):
    """
    Decodes the Unix timestamp embedded in the Google "ei" URL parameter
    (a URL-safe base64 value whose first four bytes are a little-endian Unix
    timestamp in seconds).
    """
    ei_b64 = query_params.get("ei", [None])[0]
    if not ei_b64:
        return None
    try:
        ei = base64.urlsafe_b64decode(ei_b64 + "=" * (-len(ei_b64) % 4))
        return parse_unix_seconds(struct.unpack("<I", ei[0:4])[0])
    except (binascii.Error, ValueError, struct.error):
        return None


def _get_sxsrf_timestamp(query_params: dict):
    """
    Decodes the millisecond Unix timestamp embedded at the end of the Google
    "sxsrf" URL parameter (e.g. "APpeQns...AMQ:1787847278695").
    """
    sxsrf = query_params.get("sxsrf", [None])[0]
    if not sxsrf or ":" not in sxsrf:
        return None
    ms = sxsrf.rsplit(":", 1)[1]
    if not ms.isdigit():
        return None
    seconds = int(ms) / 1000
    if not 1e9 <= seconds <= 4.1e9:  # sanity: 2001-2100
        return None
    return parse_unix_ms(int(ms))


def _get_encoded_param_fields(query_params: dict, param: str):
    """
    Returns (client_strings, query_strings) decoded from a base64 protobuf
    URL parameter such as gs_lp/gs_lcp.
    """
    value = query_params.get(param, [None])[0]
    if not value:
        return None, None
    fields = decode_base64_protobuf_strings(value)
    return fields.get(ENCODED_CLIENT_FIELD), fields.get(ENCODED_QUERY_FIELD)


def _get_ai_search_details(raw_url: str):
    """
    Parses a Google search URL for AI Mode and encoded query artifacts.
    Returns None for URLs which carry no AI Mode or encoded query markers
    (those are reported by the "Google searches" artifact).
    """
    url = urllib.parse.urlsplit(raw_url)
    query = urllib.parse.parse_qs(url.query)
    udm = query.get("udm", [None])[0]
    has_encoded_param = any(param in query for param in ENCODED_QUERY_PARAMS)

    if udm != AI_MODE_UDM_CODE and "mq" not in query and not has_encoded_param:
        return None

    gs_lp_clients, gs_lp_queries = _get_encoded_param_fields(query, "gs_lp")
    gs_lcp_clients, gs_lcp_queries = _get_encoded_param_fields(query, "gs_lcp")

    return {
        "search term": query.get("q", [None])[0],
        "original search term (oq)": query.get("oq", [None])[0],
        "ai mode": udm == AI_MODE_UDM_CODE,
        "udm vertical code": udm,
        "ai mode follow-up query (mq)": query.get("mq", [None])[0],
        "decoded search term (gs_lp)": gs_lp_queries[0] if gs_lp_queries else None,
        "decoded search term (gs_lcp)": gs_lcp_queries[0] if gs_lcp_queries else None,
        "gs client": (gs_lp_clients or gs_lcp_clients or [None])[0],
        "ei session start timestamp": _get_ei_timestamp(query),
        "sxsrf timestamp": _get_sxsrf_timestamp(query),
        "original url": raw_url,
    }


def _get_search_details(raw_url):
    url = urllib.parse.urlsplit(raw_url)
    query = urllib.parse.parse_qs(url.query)
    search_term = query.get("q", [None])[0]

    if search_term is None:
        return None

    return {"search term": search_term,
            "ei session start timestamp": _get_ei_timestamp(query)}


def _session_storage_timestamp(sess_rec, url_match_end: int, value: str):
    """
    Determines the timestamp for an embedded search URL found in a session
    storage value. Prefers the Unix microsecond timestamp in the row field
    following the URL; falls back to the millisecond timestamp encoded in the
    record key (as used by the "hsb;" search box records).
    """
    micros_match = SESSION_MICROS_PATTERN.match(value[url_match_end:url_match_end + 32])
    if micros_match is not None:
        micros = int(micros_match.group(1))
        if 1e15 <= micros <= 4.1e15:  # sanity: 2001-2100
            return EPOCH + datetime.timedelta(microseconds=micros)

    try:
        return parse_unix_ms(int(sess_rec.key.split(";;", 1)[1]))
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def google_ai_mode_search_urls(
        profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    """
    Recovers Google AI Mode (udm=50) searches and URLs carrying encoded query
    data from history, cache and session storage. In addition to the plain
    search term, the recovered rows include the AI Mode follow-up query (mq),
    the query text embedded in the base64 gs_lp/gs_lcp protobuf parameters, and
    the timestamps embedded in sxsrf / session storage rows.
    """
    results = []

    def add_result(search_details, source: str, location, domain, timestamp, url: str):
        result = {
            "source": source,
            "location": location,
            "domain": domain,
            "timestamp": timestamp,
        }
        result.update(search_details)
        results.append(result)

    for history_rec in profile.iterate_history_records(url=SEARCH_URL_PATTERN):
        search_details = _get_ai_search_details(history_rec.url)
        if search_details is None:
            continue
        add_result(search_details, "History", history_rec.record_location,
                   urllib.parse.urlparse(history_rec.url).hostname, history_rec.visit_time,
                   history_rec.url)

    for cache_rec in profile.iterate_cache(url=SEARCH_URL_PATTERN, omit_cached_data=True):
        cache_url = cache_rec.key.url
        search_details = _get_ai_search_details(cache_url)
        if search_details is None:
            continue
        add_result(search_details, "Cache URLs", str(cache_rec.metadata_location),
                   urllib.parse.urlparse(cache_url).hostname,
                   cache_rec.metadata.request_time if cache_rec.metadata is not None else None,
                   cache_url)

    for sess_rec in profile.iter_session_storage(host=re.compile(r"^https://www\.google")):
        if not isinstance(sess_rec.value, str):
            continue
        for url_match in SESSION_SEARCH_URL_PATTERN.finditer(sess_rec.value):
            search_details = _get_ai_search_details(url_match.group(0))
            if search_details is None:
                continue
            add_result(search_details, "Session Storage", sess_rec.record_location,
                       urllib.parse.urlparse(sess_rec.host).hostname,
                       _session_storage_timestamp(sess_rec, url_match.end(), sess_rec.value),
                       url_match.group(0))

    results.sort(key=lambda x: x["timestamp"] or datetime.datetime(1601, 1, 1))
    return ArtifactResult(results)


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

    for cache_rec in profile.iterate_cache(url=SEARCH_URL_PATTERN, omit_cached_data=True):
        cache_url = cache_rec.key.url
        search_details = _get_search_details(cache_url)
        if search_details is None:
            continue

        cache_rec_details = {
            "source": "Cache URLs",
            "location": str(cache_rec.metadata_location),
            "domain": urllib.parse.urlparse(cache_url).hostname,
            "timestamp": cache_rec.metadata.request_time if cache_rec.metadata is not None else None
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


def _get_translate_details(raw_url: str):
    """
    Parses a Google Translate URL (web UI, webpage translation, legacy
    hash-based format, or translate_a API call) for the translation details.
    Returns None for URLs which carry no translation content (e.g. the
    Translate homepage).
    """
    url = urllib.parse.urlsplit(raw_url)
    query = urllib.parse.parse_qs(url.query)

    # the API carries the text in "q" (repeated for multi-segment texts)
    q_values = query.get("q")
    if q_values:
        text = " ".join(q_values)
    else:
        text = query.get("text", [None])[0]

    sl = query.get("sl", [None])[0]
    tl = query.get("tl", [None])[0]
    translated_page = query.get("u", [None])[0]

    # legacy hash-based format: .../#sl/tl/text
    if text is None:
        hash_match = TRANSLATE_HASH_URL_PATTERN.search(raw_url)
        if hash_match:
            sl = sl or hash_match.group("sl")
            tl = tl or hash_match.group("tl")
            text = urllib.parse.unquote(hash_match.group("text"))

    if not text and not translated_page:
        return None

    return {
        "source text": text,
        "source language": sl,
        "target language": tl,
        "detected source language": None,
        "translated text": None,
        "translated page (u)": translated_page,
        "interface language": query.get("hl", [None])[0],
        "operation": query.get("op", [None])[0],
        "original url": raw_url,
    }


def _parse_translate_api_response(data: bytes, log_func: LogFunction, location) -> dict:
    """
    Extracts the translated text and detected source language from a cached
    translate_a/single response body (a JSON array whose first element holds
    the per-sentence translations and whose third element is the detected
    source language, e.g. [[["Hola mundo!","Hello world!",null,null,10]
    ],null,"en",...]). Returns a dict of the extractable fields.
    """
    details = {"translated text": None, "detected source language": None}
    if not data:
        return details
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        log_func(f"Warning: could not parse a Google Translate API response ({e}). "
                 f"Skipping content: {location}")
        return details

    if isinstance(parsed, list):
        if parsed and isinstance(parsed[0], list):
            sentences = [chunk[0] for chunk in parsed[0]
                         if isinstance(chunk, list) and chunk and isinstance(chunk[0], str)]
            if sentences:
                details["translated text"] = " ".join(sentences)
        if len(parsed) > 2 and isinstance(parsed[2], str):
            details["detected source language"] = parsed[2]
    return details


def google_translate(profile: BrowserProfileProtocol, log_func: LogFunction,
                     storage: ArtifactStorage) -> ArtifactResult:
    """
    Recovers Google Translate activity: what text was translated, between
    which languages, which web pages were translated, and (where the API
    responses survived in the Cache) the resulting translated text.
    """
    results = []

    for history_rec in profile.iterate_history_records(url=TRANSLATE_URL_PATTERN):
        details = _get_translate_details(history_rec.url)
        if details is None:
            continue
        details.update({
            "source": "History",
            "timestamp": history_rec.visit_time,
            "location": history_rec.record_location,
        })
        results.append(details)

    for cache_rec in profile.iterate_cache(url=TRANSLATE_URL_PATTERN, omit_cached_data=True):
        if TRANSLATE_API_URL_PATTERN.search(cache_rec.key.url):
            continue  # reported from the API response loop below, with content
        details = _get_translate_details(cache_rec.key.url)
        if details is None:
            continue
        details.update({
            "source": "Cache URLs",
            "timestamp": cache_rec.metadata.request_time if cache_rec.metadata is not None else None,
            "location": str(cache_rec.metadata_location),
        })
        results.append(details)

    # Cached translate_a API responses carry the translated output itself
    for cache_rec in profile.iterate_cache(url=TRANSLATE_API_URL_PATTERN):
        details = _get_translate_details(cache_rec.key.url)
        if details is None:
            continue
        details.update(_parse_translate_api_response(
            cache_rec.data, log_func, cache_rec.data_location))
        details.update({
            "source": "Cache response",
            "timestamp": cache_rec.metadata.request_time if cache_rec.metadata is not None else None,
            "location": str(cache_rec.data_location),
        })
        results.append(details)

    results.sort(key=lambda x: x["timestamp"] or datetime.datetime(1601, 1, 1))
    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "Google",
        "Google searches",
        "Recovers google searches from URLs in history, session storage, cache",
        "0.5",
        google_search_urls,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Google",
        "Google AI Mode searches",
        "Recovers Google AI Mode (udm=50) searches and encoded query data (mq follow-up "
        "queries, base64 gs_lp/gs_lcp protobuf query blobs, embedded sxsrf/microsecond "
        "timestamps) from URLs in history, session storage, cache",
        "0.1",
        google_ai_mode_search_urls,
        ReportPresentation.table,
        timestamp_field_names=("timestamp", "ei session start timestamp", "sxsrf timestamp")
    ),
    ArtifactSpec(
        "Google",
        "Google Translate",
        "Recovers Google Translate queries (source and target languages, translated text, "
        "pages) from URLs in history and cache, and translated responses where cached",
        "0.1",
        google_translate,
        ReportPresentation.table,
        timestamp_field_names=("timestamp",)
    ),
)

