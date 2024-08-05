from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from ccl_chromium_reader import ChromiumProfileFolder
from util.profile_folder_protocols import BrowserProfileProtocol


def dump_history(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    # TODO: Some of these fields are Chromium specific and may need tweaking for other browsers/standard interface
    results = []
    is_chrome = isinstance(profile, ChromiumProfileFolder)
    for rec in profile.iterate_history_records():
        data = {
            "record location": rec.record_location,
            "title": rec.title,
            "url": rec.url,
            "visit time": rec.visit_time,

        }
        if is_chrome:
            data.update(
                {
                    "transition core": rec.transition.core.name,
                    "transition qualifiers": ", ".join(q.name for q in rec.transition.qualifier),
                    "parent record id": rec.parent_visit_id if rec.has_parent else "None"
                }
            )
        results.append(data)
    #
    # results = [
    #     {
    #         "record location": rec.record_location,
    #         "title": rec.title,
    #         "url": rec.url,
    #         "visit time": rec.visit_time,
    #         "transition core": rec.transition.core.name,
    #         "transition qualifiers": ", ".join(q.name for q in rec.transition.qualifier),
    #         "parent record id": rec.parent_visit_id if rec.has_parent else "None"
    #     }
    #     for rec in profile.iterate_history_records()
    # ]

    return ArtifactResult(results)


def dump_downloads(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    # TODO: Some of these fields are Chromium specific and may need tweaking for other browsers/standard interface
    results = []
    is_chrome = isinstance(profile, ChromiumProfileFolder)

    for rec in profile.iter_downloads():
        data = {
            "record location": rec.record_location,
            "URL": rec.url,
            "download location": rec.target_path,
            "size": rec.file_size,
            "start time": rec.start_time,
            "end time": rec.end_time
        }
        if is_chrome:
            data.update({
                "hash": rec.hash,
                "download URL chain": " - ".join(rec.url_chain),
                "tab url": rec.tab_url,
            })

    # results = [
    #     {
    #         "record location": rec.record_location,
    #         "URL": rec.url,
    #         "download location": rec.target_path,
    #         "size": rec.file_size,
    #         "hash": rec.hash,
    #         "download URL chain": " - ".join(rec.url_chain),
    #         "tab url": rec.tab_url,
    #         "start time": rec.start_time,
    #         "end time": rec.end_time
    #     }
    #
    #     for rec in profile.iter_downloads()
    # ]
    return ArtifactResult(results)


def dump_localstorage(profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
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
        profile: BrowserProfileProtocol, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
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
        "0.2",
        dump_history,
        ReportPresentation.table),
    ArtifactSpec(
        "Data Dump",
        "Downloads",
        "Dumps Download Records",
        "0.2",
        dump_downloads,
        ReportPresentation.table),
    ArtifactSpec(
        "Data Dump",
        "Localstorage",
        "Dumps Localstorage Records",
        "0.2",
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
