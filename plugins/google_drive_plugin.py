import re
import datetime

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from ccl_chromium_reader import ChromiumProfileFolder
from util.profile_folder_protocols import BrowserProfileProtocol

FOLDERS_URL_PATTERN = re.compile(r"^https://drive.google.com/drive/folders/")
FILES_URL_PATTERN = re.compile(r"^https://drive.google.com/file/d/")
DOCS_URL_PATTERN = re.compile(r"^https://docs.google.com/(?P<service>\w+?)/d/")

THUMBNAIL_URL_PATTERN_1 = re.compile(r"googleusercontent\.com/fife.+w\d{2,4}-h\d{2,4}")
THUMBNAIL_URL_PATTERN_2 = re.compile(r"drive.fife.usercontent.google.com/u.+w\d{2,4}-h\d{2,4}")

EPOCH = datetime.datetime(1970, 1, 1)


def parse_unix_ms(ms):
    return EPOCH + datetime.timedelta(milliseconds=ms)


def _matches_file_listing_pattern(s: str):
    return bool(FOLDERS_URL_PATTERN.match(s) or FILES_URL_PATTERN.match(s) or DOCS_URL_PATTERN.match(s))


def _matches_thumbnail_pattern(s: str):
    return bool(THUMBNAIL_URL_PATTERN_1.search(s) or THUMBNAIL_URL_PATTERN_2.search(s))


def folders_and_files(
        profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    for history_rec in profile.iterate_history_records(url=_matches_file_listing_pattern):
        if FOLDERS_URL_PATTERN.match(history_rec.url):
            # page title will be structured as: "My Drive - Google Drive"
            folder_name = history_rec.title.rsplit(" - ", 1)[0]
            results.append({
                "id": history_rec.record_location,
                "type": "Folder",
                "name": folder_name,
                "url": history_rec.url,
                "timestamp": history_rec.visit_time
            })
        elif FILES_URL_PATTERN.match(history_rec.url):
            # page title will be structured as: "screenshot.png - Google Drive"
            file_name = history_rec.title.rsplit(" - ", 1)[0]
            results.append({
                "id": history_rec.record_location,
                "type": "File",
                "name": file_name,
                "url": history_rec.url,
                "timestamp": history_rec.visit_time
            })
        elif docs_match := DOCS_URL_PATTERN.match(history_rec.url):
            # page title will be structured as: "Untitled spreadsheet - Google Sheets"
            doc_name = history_rec.title.rsplit(" - ", 1)[0]
            service = docs_match.group("service").title()
            results.append({
                "id": history_rec.record_location,
                "type": service,
                "name": doc_name,
                "url": history_rec.url,
                "timestamp": history_rec.visit_time
            })

    results.sort(key=lambda x: x["timestamp"])
    return ArtifactResult(results)


def thumbnails(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    has_response_time = isinstance(profile, ChromiumProfileFolder)
    results = []
    for idx, rec in enumerate(profile.iterate_cache(url=_matches_thumbnail_pattern)):
        if rec.metadata:
            content_disposition = rec.metadata.get_attribute("content-disposition")[0]
            cache_filename = re.search(r"filename=\"(.+?)\"", content_disposition).group(1)
            out_filename = f"{idx}_{cache_filename}"
        else:
            out_filename = f"{idx}_"

        with storage.get_binary_stream(out_filename) as file_out:
            file_out.write(rec.data)

        log_func(f"Exporting thumbnail to: {file_out.get_file_location_reference()}")

        results.append({
            "url": rec.key.url,
            "cache request time": rec.metadata.request_time if rec.metadata else None,
            "cache response time": rec.metadata.response_time if has_response_time and rec.metadata else None,
            "extracted file reference": file_out.get_file_location_reference()
        })

    results.sort(key=lambda x: x["cache request time"] or datetime.datetime(1601, 1, 1))

    return ArtifactResult(results)


def timeline_usage(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []

    for rec in profile.iter_session_storage("https://drive.google.com/", key="ui:tabFirstStartTimeMsec"):
        results.append({
            "source": "Session Storage",
            "id": rec.record_location,
            "type": "Tab first start",
            "timestamp": parse_unix_ms(int(rec.value))
        })

    results.sort(key=lambda x: x["timestamp"])
    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "Google Drive",
        "Google Drive Files and Folders",
        "Recovers Google Drive and Docs folder and file names (and urls) from history records",
        "0.2",
        folders_and_files,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Google Drive",
        "Google Drive Thumbnails",
        "Recovers Google Drive thumbnails from the cache",
        "0.2",
        thumbnails,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Google Drive",
        "Google Drive Usage",
        "Recovers indications of Google Drive usage",
        "0.2",
        timeline_usage,
        ReportPresentation.table
    ),
)
