import typing

from dataclasses import dataclass
from collections.abc import Callable
from ccl_chromium_reader import ChromiumProfileFolder


JsonableType = typing.Union[None, int, float, str, bool, list["JsonableType"], dict[str, "JsonableType"]]
LogFunction = Callable[[str], None]
ArtifactFunction = Callable[[ChromiumProfileFolder, LogFunction], "ArtifactResult"]


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

