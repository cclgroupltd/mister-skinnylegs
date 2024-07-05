import base64
import json
import mimetypes
import re
import datetime
import struct
import urllib.parse

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from ccl_chromium_reader import ChromiumProfileFolder

# TODO: Look at session tracking via x-usersessionid in headers


_GUID_FRAGMENT = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
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

DOWNLOAD_URL_PATTERN = re.compile(r"sharepoint.com/.+/_layouts/\d{2}/download.aspx")

DOCUMENT_VIEW_URL_PATTERN = re.compile(r"sharepoint.com/.+/_layouts/15/(Doc.asp|doc2.aspx)")

CACHE_ACTIVITY_PATTERNS = [
    DOWNLOAD_URL_PATTERN
]

HISTORY_ACTIVITY_PATTERNS = [
    DOCUMENT_VIEW_URL_PATTERN
]

THUMB_UNIQUE_ID_PATTERN = re.compile(r"(?<=/items/)(?P<unique_id>" + _GUID_FRAGMENT + ")(?=/driveItem)")

NULL_GUID = "00000000-0000-0000-0000-000000000000"


def _get_sharepoint_recent_files(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage):
    file_results = []
    id_to_filename: dict[str, set[str]] = {}

    # Get files first, go thumbnail hunting afterwards
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
                "cache response timestamp": cache_record.metadata.response_time,
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


def _get_edgeworth_recent_files(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage):
    file_results = []
    id_to_filename: dict[tuple[str, str], set[str]] = {}

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
                "cache response timestamp": cache_record.metadata.response_time,
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


def get_recent_files(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []
    results.extend(_get_sharepoint_recent_files(profile, log_func, storage))
    results.extend(_get_edgeworth_recent_files(profile, log_func, storage))

    return ArtifactResult(results)


def _is_cache_activity_url(s: str) -> bool:
    return any(x.search(s) for x in CACHE_ACTIVITY_PATTERNS)


__artifacts__ = (
    ArtifactSpec(
        "O365-Sharepoint",
        "O365-Sharepoint recent files",
        "Recovers recent files list and any thumbnails from API responses in the cache",
        "0.1",
        get_recent_files,
        ReportPresentation.table
    ),
)
