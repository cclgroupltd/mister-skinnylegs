import datetime
import json
import mimetypes
import re
import uuid
import urllib.parse

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from ccl_chromium_reader import ChromiumProfileFolder
from util.profile_folder_protocols import BrowserProfileProtocol


_GUID_FRAGMENT = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# -- Recent Files Patterns --
RECENT_FILES_SHAREPOINT_URL_PATTERN = re.compile(r"sharepoint.com/.+?/_api/sp.RecentFileCollection")
RECENT_FILES_EDGEWORTH_URL_PATTERN = re.compile(
    r"substrate\.office\.com/recommended/api/beta/edgeworth/(?P<method>deltasync|recent)")
SHAREPOINT_THUMB_FILES_URL_PATTERN = re.compile(
    r"sharepoint\.com/_api/v2\.1/sites/" +
    _GUID_FRAGMENT +
    "/lists/" +
    _GUID_FRAGMENT +
    "/items/" +
    _GUID_FRAGMENT +
    "/driveItem/thumbnails")
GRAPH_THUMB_FILES_URL_PATTERN = re.compile(
    r"https://graph\.microsoft\.com/v1\.0/drives/(?P<drive_id>[\w!\-]+?)/items/(?P<item_id>[0-9A-Z]+?)/thumbnail"
)

# -- Activity patterns --
# qs param in qs (and then part of the WOPIsrc embedded parameter - guid as straight hex)
DOCUMENT_EDIT_SESSION_PATTERN = re.compile(
    r"officeapps.live.com/rtc2/(findsession|signalr/(start|negotiate))")
DOWNLOAD_URL_PATTERN = re.compile(r"sharepoint.com/.+/_layouts/\d{2}/download.aspx")  # UniqueID in qs, docid in headers
EXCEL_GET_FILE_COPY_URL_PATTERN = re.compile(
    r"officeapps.live.com/x/_layouts/GetFileCopyFileHandler.aspx")  # usid and workbookFilename in qs
EXCEL_FILE_FILE_HANDLER_PATTERN = re.compile(
    r"officeapps.live.com/x/_layouts/XlFileHandler.aspx")  # usid in qs
# TODO: is "Authenticate.aspx" useful? Also seen in history.


DOCUMENT_VIEW_URL_PATTERN = re.compile(
    r"sharepoint.com/.+/_layouts/15/(Doc.asp|doc2.aspx)")  # sourcedoc and file in qs


CACHE_ACTIVITY_PATTERNS = [
    DOCUMENT_EDIT_SESSION_PATTERN,
    DOWNLOAD_URL_PATTERN,
    EXCEL_GET_FILE_COPY_URL_PATTERN,
    EXCEL_FILE_FILE_HANDLER_PATTERN,
]

HISTORY_ACTIVITY_PATTERNS = [
    DOCUMENT_VIEW_URL_PATTERN
]

DOWNLOADS_ACTIVITY_PATTERNS = [
    DOWNLOAD_URL_PATTERN
]

THUMB_UNIQUE_ID_PATTERN = re.compile(r"(?<=/items/)(?P<unique_id>" + _GUID_FRAGMENT + ")(?=/driveItem)")

NULL_GUID = "00000000-0000-0000-0000-000000000000"


def _parse_content_disposition(content_disp: str):
    splitted = content_disp.split(";")
    disp_type = splitted[0]
    params = {}
    for param in splitted[1:]:
        name, value = param.split("=", 1)
        name = name.strip()
        if name == "filename":
            params["filename"] = value
        elif name == "filename*":
            enc, value = value.split("''", 1)
            params["filename*"] = urllib.parse.unquote(value, encoding=enc.lower())

    return disp_type, params


def _get_sharepoint_recent_files(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage):
    file_results = []
    id_to_filename: dict[str, set[str]] = {}

    # Get files first, go thumbnail hunting afterwards
    has_response_time = isinstance(profile, ChromiumProfileFolder)
    for cache_record in profile.iterate_cache(url=RECENT_FILES_SHAREPOINT_URL_PATTERN):
        if not cache_record.data:
            continue
        obj = json.loads(cache_record.data.decode("utf-8"))

        if "d" in obj:
            if "DeltaSync" in obj["d"]:
                method = "DeltaSync"
                files = json.loads(obj["d"][method])["files"]  # embedded json string
            elif "GetRecentFiles" in obj["d"]:
                method = "GetRecentFiles"
                files = json.loads(obj["d"][method])  # embedded json string
            else:
                raise ValueError(f"Unexpected or missing method keys: {tuple(obj["d"].keys())}")
        else:
            raise ValueError(f"Unknown RecentFileCollectionFormat in: {cache_record.key.url}")

        for file in files:
            file = file["file"]
            file_results.append({
                "cache record location": f"{cache_record.data_location.file_name}@{cache_record.data_location.offset}",
                "cache request timestamp": cache_record.metadata.request_time,
                "cache response timestamp": cache_record.metadata.response_time if has_response_time else None,
                "api endpoint cache url": cache_record.key.url,
                "method": method,
                "source": None,
                "id": file["Id"],
                "odata id": file["@odata.id"],
                "file name": file["FileName"],
                "file url": file["SharePointItem"].get("FileUrl"),
                "file size": file.get("FileSize"),
                "file created time": file.get("FileCreatedTime"),
                "file created by": None,
                "file modified time": file.get("FileModifiedTime"),
                "file modified by": None,
                "record modified time": file.get("LastModifiedDateTime"),
                "file owner": file.get("FileOwner"),
                "sharepoint site": file["SharePointItem"]["SiteId"],
                "sharepoint web id": file["SharePointItem"]["WebId"],
                "sharepoint list id": file["SharePointItem"]["ListId"],
                "sharepoint unique id": file["SharePointItem"]["UniqueId"],
                "sharepoint parent id": file["SharePointItem"].get("ParentId"),
                "onedrive drive id": None,
                "onedrive item id": None,
                "modified by": file["SharePointItem"].get("ModifiedBy"),
                "thumbnail url": None,
                "extracted thumbnail reference": None
            })

            if file["SharePointItem"]["UniqueId"] != NULL_GUID and file["FileName"]:
                unique_id = file["SharePointItem"]["UniqueId"].lower()
                id_to_filename.setdefault(unique_id, set())
                id_to_filename[unique_id].add(file["FileName"])

    # Get the thumbs
    thumb_file_references: dict[str, list[tuple[str, str]]] = {}  # Unique ID to file reference
    for idx, cache_record in enumerate(profile.iterate_cache(url=SHAREPOINT_THUMB_FILES_URL_PATTERN)):
        unique_id_match = THUMB_UNIQUE_ID_PATTERN.search(cache_record.key.url)
        if not unique_id_match:
            raise ValueError(f"Could not find the unique ID in thumb url:\n{cache_record.key.url}")

        unique_id = unique_id_match.group("unique_id").lower()
        extension = mimetypes.guess_extension(cache_record.metadata.get_attribute("content-type")[0])
        if unique_id in id_to_filename:
            out_file_name = f"thumb_sp_{idx:04}_{unique_id}_{'; '.join(id_to_filename[unique_id])}{extension}"
        else:
            out_file_name = f"thumb_sp_{idx:04}_{unique_id}{extension}"

        with storage.get_binary_stream(out_file_name) as out:
            out.write(cache_record.data)

        thumb_file_references.setdefault(unique_id, [])
        thumb_file_references[unique_id].append((out.get_file_location_reference(), cache_record.key.url))

    # Add thumb data to relevant records
    for rec in file_results:
        if (unique_id := rec["sharepoint unique id"]) in thumb_file_references:
            rec["thumbnail url"] = "\n".join(x[1] for x in thumb_file_references[unique_id])
            rec["extracted thumbnail reference"] = "\n".join(x[0] for x in thumb_file_references[unique_id])

    return file_results


def _get_edgeworth_recent_files(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage):
    file_results = []
    id_to_filename: dict[tuple[str, str], set[str]] = {}
    has_response_time = isinstance(profile, ChromiumProfileFolder)

    # Get files first, deal with thumbnails afterwards.
    for cache_record in profile.iterate_cache(url=RECENT_FILES_EDGEWORTH_URL_PATTERN):
        if not cache_record.data:
            continue

        method = RECENT_FILES_EDGEWORTH_URL_PATTERN.search(cache_record.key.url).group("method")
        obj = json.loads(cache_record.data.decode("utf-8"))
        files = obj.get("files", [])

        for file in files:
            file_name = None
            if "title" in file:
                file_name = f"{file["title"]}.{file["extension"]}" if file.get("extension") else file["title"]

            creating_user = None
            if "user" in file.get("creation_info", {}):
                creating_user = (
                        f"{file["creation_info"]["user"]["display_name"]} - " +
                        f"{file["creation_info"]["user"].get("upn") or file["creation_info"]["user"].get("id", "")}")

            modifying_user = None
            if "user" in file.get("modification_info", {}):
                modifying_user = (
                        f"{file["modification_info"]["user"]["display_name"]} - " +
                        f"{file["modification_info"]["user"].get("upn") or file["modification_info"]["user"].get("id", "")}")

            file_results.append({
                "cache record location": f"{cache_record.data_location.file_name}@{cache_record.data_location.offset}",
                "cache request timestamp": cache_record.metadata.request_time,
                "cache response timestamp": cache_record.metadata.response_time if has_response_time else None,
                "api endpoint cache url": cache_record.key.url,
                "method": method,
                "source": file.get("source"),
                "id": file["id"],
                "odata id": None,
                "file name": file_name,
                "file url": file.get("url") or file.get("web_url"),
                "file size": file.get("file_size"),
                "file created time": file["creation_info"].get("timestamp") if file.get("creation_info") else None,
                "file created by": creating_user,
                "file modified time": file["modification_info"].get("timestamp") if file.get("modification)info") else None,
                "file modified by": modifying_user,
                "record modified time": file["last_store_modified_datetime"],
                "file owner": None,
                "sharepoint site": file["sharepoint_info"]["site_id"] if file.get("sharepoint_info") else None,
                "sharepoint web id": file["sharepoint_info"]["web_id"] if file.get("sharepoint_info") else None,
                "sharepoint list id": file["sharepoint_info"]["list_id"] if file.get("sharepoint_info") else None,
                "sharepoint unique id": file["sharepoint_info"]["unique_id"] if file.get("sharepoint_info") else None,
                "sharepoint parent id": None,
                "onedrive drive id": file["onedrive_info"]["drive_id"] if file.get("onedrive_info") else None,
                "onedrive item id": file["onedrive_info"]["item_id"] if file.get("onedrive_info") else None,
                "modified by": None,
                "thumbnail url": None,
                "extracted thumbnail reference": None
            })

            od_drive_id = file["onedrive_info"]["drive_id"] if file.get("onedrive_info") else None
            od_item_id = file["onedrive_info"]["item_id"] if file.get("onedrive_info") else None

            if od_drive_id and od_item_id and file_name:
                id_to_filename.setdefault((od_drive_id, od_item_id), set())
                id_to_filename[(od_drive_id, od_item_id)].add(file_name)

    # Get thumbnails
    thumb_file_references: dict[tuple[str, str], list[tuple[str, str]]] = {}  # Unique ID to file reference
    for idx, cache_record in enumerate(profile.iterate_cache(url=GRAPH_THUMB_FILES_URL_PATTERN)):
        if not cache_record.data:
            continue

        thumb_url_match = GRAPH_THUMB_FILES_URL_PATTERN.match(cache_record.key.url)
        od_drive_id = thumb_url_match.group("drive_id")
        od_item_id = thumb_url_match.group("item_id")
        key = (od_drive_id, od_item_id)
        extension = mimetypes.guess_extension(cache_record.metadata.get_attribute("content-type")[0])

        if key in id_to_filename:
            out_file_name = f"thumb_gr_{idx:04}_{od_drive_id}_{od_item_id}_{'; '.join(id_to_filename[key])}{extension}"
        else:
            out_file_name = f"thumb_gr_{idx:04}_{od_drive_id}_{od_item_id}{extension}"

        with storage.get_binary_stream(out_file_name) as out:
            out.write(cache_record.data)

        thumb_file_references.setdefault(key, [])
        thumb_file_references[key].append((out.get_file_location_reference(), cache_record.key.url))

    # Assign thumb references to records
    for rec in file_results:
        if rec["onedrive drive id"] and rec["onedrive item id"]:
            key = (rec["onedrive drive id"], rec["onedrive item id"])
            if key in thumb_file_references:
                rec["thumbnail url"] = "\n".join(x[1] for x in thumb_file_references[key])
                rec["extracted thumbnail reference"] = "\n".join(x[0] for x in thumb_file_references[key])

    return file_results


def get_recent_files(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []
    results.extend(_get_sharepoint_recent_files(profile, log_func, storage))
    results.extend(_get_edgeworth_recent_files(profile, log_func, storage))

    return ArtifactResult(results)


def _is_cache_activity_url(s: str) -> bool:
    return any(x.search(s) for x in CACHE_ACTIVITY_PATTERNS)


def _is_history_activity_url(s: str) -> bool:
    return any(x.search(s) for x in HISTORY_ACTIVITY_PATTERNS)


def _is_downloads_activity_url(s: str) -> bool:
    return any(x.search(s) for x in DOWNLOADS_ACTIVITY_PATTERNS)


def get_activity(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []
    has_response_time = isinstance(profile, ChromiumProfileFolder)
    # Stuff from the cache
    for cache_rec in profile.iterate_cache(url=_is_cache_activity_url):
        if cache_rec.metadata is None:
            continue  # TODO: is it worth still harvesting the URLs as untimed events?

        query = urllib.parse.parse_qs(urllib.parse.urlparse(cache_rec.key.url).query)

        if DOCUMENT_EDIT_SESSION_PATTERN.search(cache_rec.key.url):
            # get ID for file from embedded query string
            embedded_query = urllib.parse.parse_qs(urllib.parse.unquote(query["qs"][0]))
            wopi_src = embedded_query["WOPIsrc"][0]
            file_unique_id = None
            if url_match := re.search(r"wopi.ashx/files/(?P<guid>[0-9a-f]{32})", wopi_src):
                file_unique_id = str(uuid.UUID(url_match.group("guid")))

            results.append({
                "source": "Cache",
                "timestamp": cache_rec.metadata.request_time,
                "user session id": cache_rec.metadata.get_attribute("x-usersessionid")[0],
                "user ip address": cache_rec.metadata.get_attribute("x-userhostaddress")[0],
                "event type": "Edit/View Session",
                "site host": None,
                "site sharepoint id": None,
                "file unique sharepoint id": file_unique_id,
                "filename": None,  # could correlate using file listings

                "cache request timestamp": cache_rec.metadata.request_time,
                "cache response timestamp": cache_rec.metadata.response_time if has_response_time else None,
                "cache_url": cache_rec.key.url,
                "cache_meta_location": str(cache_rec.metadata_location),
            })
        elif DOWNLOAD_URL_PATTERN.search(cache_rec.key.url):
            doc_id = cache_rec.metadata.get_attribute("docid")[0]
            host, site_id, file_unique_id = doc_id.split("_", 2)
            disp_type, filenames = _parse_content_disposition(
                cache_rec.metadata.get_attribute("content-disposition")[0])
            filename = filenames.get("filename*") or filenames.get("filename")

            results.append({
                "source": "Cache",
                "timestamp": cache_rec.metadata.request_time,
                "user session id": None,
                "user ip address": None,
                "event type": "Download",
                "site host": None,
                "site sharepoint id": site_id,
                "file unique sharepoint id": file_unique_id,
                "filename": filename,

                "cache request timestamp": cache_rec.metadata.request_time,
                "cache response timestamp": cache_rec.metadata.response_time if has_response_time else None,
                "cache_url": cache_rec.key.url,
                "cache_meta_location": str(cache_rec.metadata_location),
            })
        elif EXCEL_GET_FILE_COPY_URL_PATTERN.search(cache_rec.key.url):
            filename = query.get("workbookFilename")[0]

            results.append({
                "source": "Cache",
                "timestamp": cache_rec.metadata.request_time,
                "user session id": cache_rec.metadata.get_attribute("x-usersessionid")[0],
                "user ip address": None,
                "event type": "Download",
                "site host": None,
                "site sharepoint id": None,
                "file unique sharepoint id": None,
                "filename": filename,

                "cache request timestamp": cache_rec.metadata.request_time,
                "cache response timestamp": cache_rec.metadata.response_time if has_response_time else None,
                "cache_url": cache_rec.key.url,
                "cache_meta_location": str(cache_rec.metadata_location),
            })
        elif EXCEL_FILE_FILE_HANDLER_PATTERN.search(cache_rec.key.url):
            disp_type, filenames = _parse_content_disposition(
                cache_rec.metadata.get_attribute("content-disposition")[0])
            filename = filenames.get("filename*") or filenames.get("filename")

            results.append({
                "source": "Cache",
                "timestamp": cache_rec.metadata.request_time,
                "user session id": cache_rec.metadata.get_attribute("x-usersessionid")[0],
                "user ip address": None,
                "event type": "Download",
                "site host": None,
                "site sharepoint id": None,
                "file unique sharepoint id": None,
                "filename": filename,

                "cache request timestamp": cache_rec.metadata.request_time,
                "cache response timestamp": cache_rec.metadata.response_time if has_response_time else None,
                "cache_url": cache_rec.key.url,
                "cache_meta_location": str(cache_rec.metadata_location),
            })

    # History things
    for history_rec in profile.iterate_history_records(url=_is_history_activity_url):
        url = urllib.parse.urlparse(history_rec.url)
        query = urllib.parse.parse_qs(url.query)

        if DOCUMENT_VIEW_URL_PATTERN.search(history_rec.url):
            results.append({
                "source": "History",
                "timestamp": history_rec.visit_time,

                "user session id": None,
                "user ip address": None,
                "event type": "File Open",
                "site host": url.hostname,
                "site sharepoint id": None,
                "file unique sharepoint id": query.get("sourcedoc", [""])[0].lower().strip("{}"),
                "filename": query.get("file", [""])[0],

                "history_url": history_rec.url,
                "history_id": history_rec.record_location,

            })

    # Downloads
    # We treat Chrome differently because you can have multiple versions of the same download and we need to find the
    # best one for our purposes:
    is_chrome = isinstance(profile, ChromiumProfileFolder)
    if isinstance(profile, ChromiumProfileFolder):
        downloads = {}  # collate downloads first to get the best version
        chrome_epoch = datetime.datetime(1601, 1, 1)
        for download in profile.iter_downloads(download_url=_is_downloads_activity_url):
            if download.guid not in downloads:
                downloads[download.guid] = download
            elif ((download.hash and not downloads[download.guid].hash) or
                  (downloads[download.guid].end_time == chrome_epoch and download.end_time > chrome_epoch)):
                downloads[download.guid] = download
        download_recs = downloads.values()
    else:
        download_recs = profile.iter_downloads(download_url=_is_downloads_activity_url)

    for download in download_recs:
        url = urllib.parse.urlparse(download.url)
        query = urllib.parse.parse_qs(url.query)

        if DOWNLOAD_URL_PATTERN.search(download.url):
            results.append({
                "source": f"Downloads ({download.record_location})",
                "timestamp": download.start_time,

                "user session id": None,
                "user ip address": None,
                "event type": "Download",
                "site host": url.hostname,
                "site sharepoint id": None,
                "file unique sharepoint id": query.get("UniqueId", [""])[0].lower().strip("{}"),
                "filename": None,
                "download_size": download.file_size,
                "download_target_path": download.target_path,
                "download_start_timestamp": download.start_time,
                "download_end_timestamp": download.end_time,
                "download_record_id": download.record_location,
                "download_sha256": download.hash,
                "download_guid": download.guid
            })

    results.sort(key=lambda x: x["timestamp"])
    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "O365-Sharepoint",
        "O365-Sharepoint recent files",
        "Recovers recent files list and any thumbnails from API responses in the cache for Sharepoint and O365",
        "0.2",
        get_recent_files,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "O365-Sharepoint",
        "O365-Sharepoint user activity",
        "Recovers artifacts related to user activity (viewing, editing, downloading, etc.) for Sharepoint and O365",
        "0.2",
        get_activity,
        ReportPresentation.table
    ),
)
