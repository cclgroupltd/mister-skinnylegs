import json
import re
import datetime
import urllib.parse

from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from ccl_chromium_reader import ChromiumProfileFolder


EPOCH = datetime.datetime(1970, 1, 1)


def parse_unix_ms(ms):
    return EPOCH + datetime.timedelta(milliseconds=ms)


def uax_records(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    result = []
    for rec in profile.iter_session_storage(host=re.compile(r"dropbox\.com"), key=re.compile(r"^uxa")):
        if rec.key == "uxa.last_active_time":
            last_active_time = parse_unix_ms(int(rec.value))
            result.append(
                {"sequence": rec.leveldb_sequence_number,
                 "record type": "last active time",
                 "timestamp": str(last_active_time)})
        elif rec.key == "uxa.inaniframe.last_active_time":
            last_active_time = parse_unix_ms(int(rec.value))
            result.append(
                {"sequence": rec.leveldb_sequence_number,
                 "record type": "in ani frame last active time",
                 "timestamp": str(last_active_time)})
        elif rec.key == "uxa.visit_id":
            result.append(
                {"sequence": rec.leveldb_sequence_number,
                 "record type": "visit id",
                 "visit id": rec.value})
        elif rec.key == "uxa.previous_url":
            result.append(
                {"sequence": rec.leveldb_sequence_number,
                 "record type": "previous url",
                 "previous url": rec.value})
        elif rec.key == "uxa.clicked_link":
            clicked_link_obj = json.loads(rec.value)
            result.append(
                {"sequence": rec.leveldb_sequence_number,
                 "record type": "clicked link",
                 "visit id": clicked_link_obj["visit_id"],
                 "url": clicked_link_obj["origin_href"],
                 "time on page": clicked_link_obj["time on page"],
                 "previous url": clicked_link_obj["url"]})

    result.sort(key=lambda x: x["sequence"])
    return ArtifactResult(result)


def recovered_file_system(
        profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = set()
    for rec in profile.iterate_history_records(re.compile(r"dropbox\.com/home")):
        # example url: https://www.dropbox.com/home/Alpha/Bravo?preview=6b+Mkv.mkv
        split_url = rec.url.split("/home/", 1)
        if len(split_url) < 2:
            continue

        path = split_url[1]
        split_path = path.split("?preview=")
        folder = urllib.parse.unquote_plus(split_path[0])
        results.add(folder)

        if len(split_path) > 1:
            file_name = urllib.parse.unquote_plus(split_path[1])
            results.add(f"{folder}/{file_name}")

    return ArtifactResult([{"path": x} for x in sorted(results)])


def thumbnails(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = []
    for idx, rec in enumerate(profile.iterate_cache(re.compile(r"https://previews.dropbox.com/p/thumb/"))):
        content_disposition = rec.metadata.get_attribute("content-disposition")[0]
        cache_filename = re.search(r"filename=\"(.+?)\"", content_disposition).group(1)
        out_filename = f"{idx}_{cache_filename}"

        with storage.get_binary_stream(out_filename) as file_out:
            file_out.write(rec.data)

        log_func(f"Exporting thumbnail to: {file_out.get_file_location_reference()}")

        results.append({
            "url": rec.key.url,
            "cache request time": str(rec.metadata.request_time),
            "cache response time": str(rec.metadata.response_time),
            "extracted file reference": file_out.get_file_location_reference()
        })

    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "Dropbox",
        "Dropbox Session Storage User Activity",
        "Recovers user activity from 'uxa' records in Session Storage",
        "0.1",
        uax_records,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Dropbox",
        "Dropbox File System",
        "Recovers a partial file system from URLs in the history",
        "0.1",
        recovered_file_system,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Dropbox",
        "Dropbox Thumbnails",
        "Recovers thumbnails for files stored in Dropbox",
        "0.1",
        thumbnails,
        ReportPresentation.table
    ),
)
