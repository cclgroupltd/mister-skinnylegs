from util.artifact_utils import ArtifactResult, ArtifactSpec
from ccl_chromium_reader import ChromiumProfileFolder
from collections.abc import Callable


def example_artifact1(profile: ChromiumProfileFolder, log_func: Callable[[str], None]) -> ArtifactResult:
    log_func("Logging inside of example_artifact1")
    result = ArtifactResult([{"url": rec.url} for rec in profile.history.iter_history_records(None)])
    return result


def example_artifact2(profile: ChromiumProfileFolder, log_func: Callable[[str], None]) -> ArtifactResult:
    log_func("Logging inside of example_artifact2")
    result = ArtifactResult([{"host": rec} for rec in profile.iter_local_storage_hosts()])
    return result


__artifacts__ = (
    ArtifactSpec("Example artifact 1", "Example which returns all URLs from history", example_artifact1),
    ArtifactSpec("Example artifact 2", "Example which returns all hosts for local storage", example_artifact2)
)
