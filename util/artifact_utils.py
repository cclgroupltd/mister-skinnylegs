from dataclasses import dataclass
from collections.abc import Callable
from ccl_chromium_reader import ChromiumProfileFolder
import typing

JsonableType = typing.Union[None, int, str, bool, list["JsonableType"], dict[str, "JsonableType"]]


@dataclass(frozen=True)
class ArtifactResult:
    result: JsonableType


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    description: str
    method: Callable[[ChromiumProfileFolder], ArtifactResult]


