from util.artifact_utils import ArtifactResult, ArtifactSpec, LogFunction, ReportPresentation, ArtifactStorage
from ccl_chromium_reader import ChromiumProfileFolder


def example_artifact1(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    log_func("Logging inside of example_artifact1")
    result = ArtifactResult([
        {"id": rec.rec_id, "title": rec.title, "url": rec.url} for rec in profile.history.iter_history_records(None)
    ])
    return result


def example_artifact2(profile: ChromiumProfileFolder, log_func: LogFunction, storage: ArtifactStorage) -> ArtifactResult:
    log_func("Logging inside of example_artifact2")
    result = ArtifactResult([{"host": rec} for rec in profile.iter_local_storage_hosts()])
    return result


__artifacts__ = (
    ArtifactSpec(
        "Examples",
        "Example artifact 1",
        "Example which returns all Titles and URLs from history",
        "0.0.2",
        example_artifact1,
        ReportPresentation.table
    ),
    ArtifactSpec(
        "Examples",
        "Example artifact 2",
        "Example which returns all hosts for local storage",
        "0.0.1",
        example_artifact2,
        ReportPresentation.table
    )
)
