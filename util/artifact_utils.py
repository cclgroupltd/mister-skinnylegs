import typing
import enum

from dataclasses import dataclass
from collections.abc import Callable
from ccl_chromium_reader import ChromiumProfileFolder


JsonableType = typing.Union[None, int, float, str, bool, list["JsonableType"], dict[str, "JsonableType"]]
LogFunction = Callable[[str], None]
ArtifactFunction = Callable[[ChromiumProfileFolder, LogFunction], "ArtifactResult"]


class ReportPresentation(enum.Enum):
    """
    Report presentations for artifacts. These inform the host that results adhere to a format that may be processed
    in a known way.

    custom: the output requires a custom presentation and will be processed by another tool/script
    table: the output is a list of dicts, which can be used with a csv.DictWriter fields should be collated
      from the keys of each dict in the list
    """
    custom = 0
    table = 1


@dataclass(frozen=True)
class ArtifactResult:
    result: JsonableType


@dataclass(frozen=True)
class ArtifactSpec:
    service: str
    name: str
    description: str
    version: str
    function: ArtifactFunction
    presentation: ReportPresentation = ReportPresentation.custom

