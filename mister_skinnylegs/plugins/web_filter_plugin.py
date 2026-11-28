"""
Plugin for recovering web filter ("block page") artifacts from browser
history and Cache data.

Managed devices - school-issued laptops in particular, but also
home/parental-control setups - intercept disallowed browsing and redirect the
user to a vendor "block page". These hits remain in the browser's history and
cache even though the blocked site itself was never loaded, and the block
page URL embeds the blocked target, the blocking reason/category and often
the user and device identity, making them strong corroboration of what was
attempted, by whom and when.

The per-vendor URL schemas implemented here are derived from real archived
block page examples (Internet Archive captures of blocked.goguardian.com,
blocked.<region>.linewize.net, securly.com/blocked and block.si/block.php):

* GoGuardian:  blocked.goguardian.com/?ctx=<base64>&sum=<hex>&bpc=<bool>
    where ctx decodes to oi=<org id>&ou=<original url>&rs=<reason>&st=<client>
    [&sci=<n>]&v=<version>
* Linewize:    blocked.<region>.linewize.net/blocked?url=<domain>&deviceid=...
    &user=...&rule=<base64 rule name>&ruleid=<uuid>&path=<blocked path>
    [&method=rule_match][&cid=<base64 of user + epoch ms>]
* Securly:     <regional>.securly.com/blocked?useremail=...&reason=...
    &categoryid=...&policyid=...&keyword=<base64>&url=<base64 blocked url>
    &ver=...&extension_id=...&lat=...&lng=...
    (older blocked.php variant: ?gnp=1&reason=domainblockedforuser&url=<domain>)
* BlockSi:     www.block.si/block.php?url=<domain>&category=<code>[&bwlist=<code>]
* Microsoft Family Safety:
    sdx.microsoft.com/family/restricted-web[-email[2]]
    [?url=<percent-encoded blocked url>][&c=<category>][&theme=<Light|Dark>]
    [&t=<Microsoft auth token>] - bare /family/restricted-web captures exist
    too; other sdx paths (e.g. /auth/...) are service pages, not block pages
* eero:        blocked.eero.com/?url=<percent-encoded blocked url>&referer=...
    &reason=<e.g. ", PHISHING">&reasoncode=&timebound=&action=deny&kind=
    &rule=&cat=&user=&zsq= (most fields are empty in the archived captures)
* Circle:      filter.meetcircle.com/<profile>/?filtered=<domain>
    &cat=<category name>&catid=<code>&reason=blocked, where <profile> is
    adults, kids or teen (category names are localised, e.g. "Redes sociales")

Lightspeed Filter block pages are served from district-local appliances and
have no archived captures under lightspeedsystems.com (blocklist/block/
blocked/filter subdomains are all empty in the Internet Archive CDX as of
2026-09), so those hosts are recognised by name only and decoded with the
generic fallback.
"""
import base64
import binascii
import datetime
import re
import urllib.parse

from mister_skinnylegs.util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from mister_skinnylegs.util.profile_folder_protocols import BrowserProfileProtocol


# Vendor host suffixes mapped to friendly names
VENDOR_HOST_SUFFIXES = (
    ("goguardian.com", "GoGuardian"),
    ("linewize.net", "Linewize"),
    ("securly.com", "Securly"),
    ("block.si", "BlockSi"),
    ("lightspeedsystems.com", "Lightspeed Filter"),
    ("sdx.microsoft.com", "Microsoft Family Safety"),
    ("eero.com", "eero"),
    ("meetcircle.com", "Circle"),
)

# Block page URL indicators applied to the parsed host/path
BLOCK_HOST_PREFIXES = ("blocked.", "filter.")
BLOCK_PATH_SUBSTRING = "/blocked"  # covers /blocked and /blocked.php
BLOCK_PATHS = ("/block", "/block.php")

# Where a vendor's domain is broader than its block page host, the archived
# captures pin the block page to specific hosts. A domain match alone (e.g.
# www.eero.com marketing pages) must NOT be treated as a block page.
VENDOR_BLOCK_HOST_PREFIXES = {
    "Lightspeed Filter": ("blocked.", "filter.", "blocklist."),
    "eero": ("blocked.",),          # blocked.eero.com/?url=... (archived 2018)
    "Circle": ("filter.",),         # filter.meetcircle.com/<profile>/ (archived 2018-2026)
}

# Block page path per vendor where the captured evidence pins one down (other
# paths on the same host are service pages, not block pages).
VENDOR_BLOCK_PATH_PREFIXES = {
    "Microsoft Family Safety": ("/family/restricted-web",),
}

EPOCH = datetime.datetime(1970, 1, 1)


def _vendor_for_host(host: str):
    for suffix, vendor in VENDOR_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix) or host.endswith(suffix):
            return vendor
    return None


def _is_block_page(url: str):
    """
    Determines whether a URL is a web filter block page. Returns the matched
    vendor name, or None where the match was purely heuristic (e.g. an
    unknown host with a /blocked path), or False where the URL does not look
    like a block page.
    """
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path or ""

    vendor = _vendor_for_host(host)
    if vendor is not None:
        required_host_prefixes = VENDOR_BLOCK_HOST_PREFIXES.get(vendor)
        if required_host_prefixes is not None and not host.startswith(required_host_prefixes):
            return False
        required_paths = VENDOR_BLOCK_PATH_PREFIXES.get(vendor)
        if required_paths is None or any(path.startswith(prefix) for prefix in required_paths):
            return vendor
        return False
    if host.startswith(BLOCK_HOST_PREFIXES):
        return None
    if BLOCK_PATH_SUBSTRING in path or path in BLOCK_PATHS:
        return None
    return False


def _block_page_url_filter(url: str) -> bool:
    """
    KeySearch-style predicate for profile.iterate_history_records/iterate_cache.
    """
    return _is_block_page(url) is not False


def _query_params_lower(url: str) -> dict:
    """
    Returns the URL's query parameters as a {lowercase name: [values]} dict,
    preserving the original values (percent-decoded).
    """
    try:
        return {name.lower(): values for name, values in
                urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True).items()}
    except ValueError:
        return {}


def _first_param(params: dict, names):
    for name in names:
        values = params.get(name)
        if values and values[0]:
            return values[0]
    return None


def _maybe_base64_text(value):
    """
    Decodes a standard base64 value to printable text, or returns None if the
    value is not base64 (e.g. a plain domain) or does not decode to printable
    UTF-8.
    """
    if not value:
        return None
    candidate = value.strip()
    try:
        raw = base64.b64decode(candidate + "=" * (-len(candidate) % 4), validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if text and all(character.isprintable() for character in text):
        return text
    return None


def _join_context(*pairs) -> str:
    """
    Formats (label, value) pairs as "label=value; label=value", skipping None
    values.
    """
    return "; ".join(f"{label}={value}" for label, value in pairs if value is not None) or None


def _decode_goguardian(url: str, params: dict) -> dict:
    # ctx is base64 over a URL-encoded "oi=..&ou=..&rs=..&st=..[&sci=..]&v=.." string
    ctx_fields = {}
    ctx = _first_param(params, ("ctx",))
    if ctx:
        decoded = _maybe_base64_text(ctx)
        if decoded and "=" in decoded:
            try:
                ctx_fields = {name.lower(): values[0] if values else None for name, values in
                              urllib.parse.parse_qs(decoded, keep_blank_values=True).items()}
            except ValueError:
                ctx_fields = {}
    return {
        "blocked url or domain": ctx_fields.get("ou"),
        "category or reason": ctx_fields.get("rs"),
        "user": None,
        "rule/policy name": None,
        "rule/policy id": None,
        "device id": None,
        "keyword": None,
        "blocked path/query": None,
        "other decoded context": _join_context(
            ("org id (oi)", ctx_fields.get("oi")),
            ("strategy (st)", ctx_fields.get("st")),
            ("sci", ctx_fields.get("sci")),
            ("ctx version (v)", ctx_fields.get("v")),
            ("sum", _first_param(params, ("sum",))),
            ("bpc", _first_param(params, ("bpc",))),
        ),
    }


def _decode_linewize(url: str, params: dict) -> dict:
    # the path parameter value runs to the end of the URL and may itself
    # contain "&" separated fields of the blocked request; method and cid are
    # split back out of the tail where present
    path = None
    method = None
    cid = None
    if "path=" in url:
        rest = url.split("path=", 1)[1]
        # method and cid sit at the tail of the path value; find both on the
        # original tail and truncate the path once at the earliest match
        cut = len(rest)
        for name in ("method", "cid"):
            match = re.search(rf"(?:^|&){name}=([^&#]*)", rest)
            if match:
                if name == "method":
                    method = match.group(1)
                else:
                    cid = match.group(1)
                cut = min(cut, match.start())
        path = rest[:cut] or None

    rule_name = _maybe_base64_text(_first_param(params, ("rule",)))

    # cid decodes to <user><epoch ms>; the trailing 13 digits are the block
    # event time (pattern consistent across archived examples)
    cid_timestamp = None
    cid_text = _maybe_base64_text(cid)
    if cid_text:
        match = re.search(r"(\d{13})$", cid_text)
        if match:
            cid_timestamp = EPOCH + datetime.timedelta(milliseconds=int(match.group(1)))

    return {
        "blocked url or domain": _first_param(params, ("url",)),
        "category or reason": None,
        "user": _first_param(params, ("user",)),
        "rule/policy name": rule_name,
        "rule/policy id": _first_param(params, ("ruleid",)),
        "device id": _first_param(params, ("deviceid",)),
        "keyword": None,
        "blocked path/query": path,
        "other decoded context": _join_context(
            ("method", method),
            ("cid", cid_text),
            ("cid timestamp (epoch ms)", cid_timestamp.isoformat() if cid_timestamp else None),
        ),
        "cid timestamp": cid_timestamp,
    }


def _decode_securly(url: str, params: dict) -> dict:
    # url and keyword values are base64 in the current schema (the older
    # blocked.php variant carries a plain domain in url). The decoded keyword
    # mirrors the search query text, where "+" denotes a space.
    blocked = _first_param(params, ("url",))
    decoded = _maybe_base64_text(blocked)
    if decoded:
        blocked = decoded
    keyword = _maybe_base64_text(_first_param(params, ("keyword",)))
    if keyword:
        keyword = urllib.parse.unquote_plus(keyword)
    return {
        "blocked url or domain": blocked,
        "category or reason": _first_param(params, ("reason",)),
        "user": _first_param(params, ("useremail", "user", "email")),
        "rule/policy name": None,
        "rule/policy id": _first_param(params, ("policyid",)),
        "device id": None,
        "keyword": keyword,
        "blocked path/query": None,
        "other decoded context": _join_context(
            ("category id", _first_param(params, ("categoryid",))),
            ("extension version", _first_param(params, ("ver",))),
            ("extension id", _first_param(params, ("extension_id",))),
            ("device lat/lng", ", ".join(filter(None, (
                _first_param(params, ("lat",)), _first_param(params, ("lng",))))) or None),
            ("gnp", _first_param(params, ("gnp",))),
        ),
    }


def _decode_blocksi(url: str, params: dict) -> dict:
    return {
        "blocked url or domain": _first_param(params, ("url",)),
        "category or reason": _first_param(params, ("category",)),
        "user": None,
        "rule/policy name": None,
        "rule/policy id": None,
        "device id": None,
        "keyword": None,
        "blocked path/query": None,
        "other decoded context": _join_context(
            ("bwlist", _first_param(params, ("bwlist",))),
        ),
    }


def _decode_microsoft_family_safety(url: str, params: dict) -> dict:
    # sdx.microsoft.com/family/restricted-web[-email[2]] captures: the blocked
    # target rides in the url parameter, c carries a category code, theme the
    # page theme, and t a long Microsoft auth token (kept truncated - it is
    # not forensically meaningful beyond its presence)
    token = _first_param(params, ("t",))
    if token:
        token = f"{token[:40]}... (len {len(token)})"
    return {
        "blocked url or domain": _first_param(params, ("url",)),
        "category or reason": _first_param(params, ("c",)),
        "user": None,
        "rule/policy name": None,
        "rule/policy id": None,
        "device id": None,
        "keyword": None,
        "blocked path/query": None,
        "other decoded context": _join_context(
            ("theme", _first_param(params, ("theme",))),
            ("auth token (t)", token),
        ),
    }


def _decode_eero(url: str, params: dict) -> dict:
    # blocked.eero.com captures: url is the percent-encoded blocked target,
    # reason and cat repeat the blocking reason (", PHISHING"), action is
    # deny, and the remaining documented fields were empty in every capture
    def clean(value):
        # ", PHISHING" -> "PHISHING"
        return value.lstrip(", ") if value else None

    reason = clean(_first_param(params, ("reason",)))
    category = clean(_first_param(params, ("cat",)))
    return {
        "blocked url or domain": _first_param(params, ("url",)),
        "category or reason": reason or category,
        "user": _first_param(params, ("user",)) or None,
        "rule/policy name": _first_param(params, ("rule",)) or None,
        "rule/policy id": None,
        "device id": None,
        "keyword": None,
        "blocked path/query": None,
        "other decoded context": _join_context(
            ("cat", category),
            ("reasoncode", _first_param(params, ("reasoncode",)) or None),
            ("timebound", _first_param(params, ("timebound",)) or None),
            ("action", _first_param(params, ("action",)) or None),
            ("kind", _first_param(params, ("kind",)) or None),
            ("referer", _first_param(params, ("referer",)) or None),
            ("zsq", _first_param(params, ("zsq",)) or None),
        ),
    }


def _decode_circle(url: str, params: dict) -> dict:
    # filter.meetcircle.com/<profile>/?filtered=<domain>&cat=<name>&catid=<n>
    # &reason=blocked - the path segment is the profile the policy applied to
    profile = (urllib.parse.urlsplit(url).path or "").strip("/").split("/")[0] or None
    return {
        "blocked url or domain": _first_param(params, ("filtered",)),
        "category or reason": _first_param(params, ("cat",)),
        "user": None,
        "rule/policy name": None,
        "rule/policy id": None,
        "device id": None,
        "keyword": None,
        "blocked path/query": None,
        "other decoded context": _join_context(
            ("profile", profile),
            ("category id", _first_param(params, ("catid",))),
            ("reason", _first_param(params, ("reason",))),
        ),
    }


def _decode_generic(url: str, params: dict) -> dict:
    # fallback for un-evidenced vendors: a conservative guess at the common
    # parameter names, with everything else preserved verbatim
    known = ("url", "u", "web_addr", "site", "target", "original_url", "blocked_url",
             "cat", "category", "reason", "block_reason", "policy", "policyname",
             "user", "username", "email", "useremail", "uid", "student", "account")
    other = "; ".join(f"{name}={value}" for name, values in sorted(params.items())
                      for value in values if name not in known)
    return {
        "blocked url or domain": _first_param(params, ("url", "u", "web_addr", "site", "target", "original_url", "blocked_url")),
        "category or reason": _first_param(params, ("cat", "category", "reason", "block_reason", "policy", "policyname")),
        "user": _first_param(params, ("user", "username", "email", "useremail", "uid", "student", "account")),
        "rule/policy name": None,
        "rule/policy id": None,
        "device id": None,
        "keyword": None,
        "blocked path/query": None,
        "other decoded context": other or None,
        "cid timestamp": None,
    }


VENDOR_DECODERS = {
    "GoGuardian": _decode_goguardian,
    "Linewize": _decode_linewize,
    "Securly": _decode_securly,
    "BlockSi": _decode_blocksi,
    "Microsoft Family Safety": _decode_microsoft_family_safety,
    "eero": _decode_eero,
    "Circle": _decode_circle,
}


def get_block_pages(profile: BrowserProfileProtocol, log_func: LogFunction,
                    storage: ArtifactStorage) -> ArtifactResult:
    """
    Recovers web filter block page URLs from history and cache keys, with the
    vendor and the decoded embedded blocked target, reason/category, user and
    device details (per the schemas documented in the module docstring).
    """
    results = []

    def add_result(url: str, source: str, timestamp, location):
        vendor = _is_block_page(url)
        if vendor is False:
            return
        params = _query_params_lower(url)
        fields = VENDOR_DECODERS.get(vendor, _decode_generic)(url, params)
        fields.update({
            "vendor": vendor,
            "source": source,
            "timestamp": timestamp,
            "original url": url,
            "location": location,
        })
        results.append(fields)

    for history_rec in profile.iterate_history_records(url=_block_page_url_filter):
        add_result(history_rec.url, "History", history_rec.visit_time,
                   f"{history_rec.record_location}")

    for cache_rec in profile.iterate_cache(url=_block_page_url_filter, omit_cached_data=True):
        add_result(cache_rec.key.url, "Cache URLs",
                   cache_rec.metadata.request_time if cache_rec.metadata is not None else None,
                   f"{cache_rec.metadata_location}")

    results.sort(key=lambda r: r["timestamp"] or datetime.datetime(1601, 1, 1))
    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "Web Filters",
        "Web Filter Block Pages",
        "Recovers web filter block page URLs (GoGuardian, Linewize, Securly, BlockSi, "
        "Lightspeed, Microsoft Family Safety, eero, Circle) from history and cache, "
        "decoding the embedded blocked target, reason/category, rule, user and device "
        "details per the vendor URL schemas",
        "0.3",
        get_block_pages,
        ReportPresentation.table,
        timestamp_field_names=("timestamp",)
    ),
)
