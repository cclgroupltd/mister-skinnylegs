from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from ccl_chromium_reader import ChromiumProfileFolder


def dump_history(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    # TODO: Some of these fields are Chromium specific and may need tweaking for other browsers/standard interface

    results = [
        {
            "record location": rec.record_location,
            "title": rec.title,
            "url": rec.url,
            "visit time": rec.visit_time,
            "transition core": rec.transition.core.name,
            "transition qualifiers": ", ".join(q.name for q in rec.transition.qualifier),
            "parent record id": rec.parent_visit_id if rec.has_parent else "None"
        }
        for rec in profile.iterate_history_records()
    ]

    return ArtifactResult(results)


def dump_downloads(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    # TODO: Some of these fields are Chromium specific and may need tweaking for other browsers/standard interface
    results = [
        {
            "record location": rec.record_location,
            "URL": rec.url_chain[-1],
            "download location": rec.target_path,
            "size": rec.total_bytes,
            "hash": rec.hash,
            "download URL chain": " - ".join(rec.url_chain),
            "tab url": rec.tab_url,
            "start time": rec.start_time,
            "end time": rec.end_time
        }

        for rec in profile.iter_downloads()
    ]
    return ArtifactResult(results)


def dump_localstorage(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = [
        {
            "record location": rec.record_location,
            "host": rec.storage_key,
            "key": rec.script_key,
            "value": rec.value
        }
        for rec in profile.iter_local_storage()
    ]

    return ArtifactResult(results)


def dump_sessionstorage(
        profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    results = [
        {
            "record location": rec.record_location,
            "host": rec.host,
            "key": rec.key,
            "value": rec.value
        }
        for rec in profile.iter_session_storage()
    ]

    return ArtifactResult(results)


__artifacts__ = (
    ArtifactSpec(
        "Data Dump",
        "History",
        "Dumps History Records",
        "0.1",
        dump_history,
        ReportPresentation.table),
    ArtifactSpec(
        "Data Dump",
        "Downloads",
        "Dumps Download Records",
        "0.1",
        dump_downloads,
        ReportPresentation.table),
    ArtifactSpec(
        "Data Dump",
        "Localstorage",
        "Dumps Localstorage Records",
        "0.1",
        dump_localstorage,
        ReportPresentation.table),
    ArtifactSpec(
        "Data Dump",
        "Sessionstorage",
        "Dumps Sessionstorage Records",
        "0.1",
        dump_sessionstorage,
        ReportPresentation.table),

)
