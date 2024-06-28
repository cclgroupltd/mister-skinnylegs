import typing
import enum
import abc

from dataclasses import dataclass
from collections.abc import Callable
from ccl_chromium_reader import ChromiumProfileFolder


JsonableType = typing.Union[None, int, float, str, bool, list["JsonableType"], dict[str, "JsonableType"]]
LogFunction = Callable[[str], None]
ArtifactFunction = Callable[[ChromiumProfileFolder, LogFunction, "ArtifactStorage"], "ArtifactResult"]


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


class ArtifactStorageBinaryStream(abc.ABC):
    def write(self, data: bytes) -> int:
        raise NotImplementedError()

    def close(self) -> None:
        raise NotImplementedError()

    def get_file_location_reference(self) -> str:
        raise NotImplementedError()

    def __enter__(self) -> "ArtifactStorageBinaryStream":
        raise NotImplementedError()

    def __exit__(self, exc_type, exc_val, exc_tb):
        raise NotImplementedError()


class ArtifactStorageTextStream(abc.ABC):
    def write(self, data: str) -> int:
        raise NotImplementedError()

    def close(self) -> None:
        raise NotImplementedError()

    def get_file_location_reference(self) -> str:
        raise NotImplementedError()

    def __enter__(self) -> "ArtifactStorageTextStream":
        raise NotImplementedError()

    def __exit__(self, exc_type, exc_val, exc_tb):
        raise NotImplementedError()


class ArtifactStorage(abc.ABC):
    def get_binary_stream(self, file_name: str) -> ArtifactStorageBinaryStream:
        """
        Returns a ArtifactStorageBinaryStream which can be used by a plugin to store report data
        :param file_name: the name of the file to be stored. This may be altered by the implementing class so the
               ArtifactStorageBinaryStream should be used to get the final file location reference
        :return: an object implementing ArtifactStorageBinaryStream
        """
        raise NotImplementedError()

    def get_text_stream(self, file_name: str) -> ArtifactStorageTextStream:
        """
        Returns a ArtifactStorageTextStream which can be used by a plugin to store report data
        :param file_name: the name of the file to be stored. This may be altered by the implementing class so the
               ArtifactStorageTextStream should be used to get the final file location reference
        :return: an object implementing ArtifactStorageTextStream
        """
        raise NotImplementedError()

