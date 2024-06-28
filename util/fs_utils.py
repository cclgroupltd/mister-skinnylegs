import pathlib
import re
import typing

from util.artifact_utils import ArtifactStorage, ArtifactStorageTextStream, ArtifactStorageBinaryStream

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}


BAD_FN_CHARACTERS = re.compile(r"[\[\]()^\s#%&!@:+={}'~\\/]")


def sanitize_filename(fn: str):
    if fn in WINDOWS_RESERVED_NAMES:
        fn = "_" + fn
    if fn.startswith("."):
        fn = "_" + fn
    fn = BAD_FN_CHARACTERS.sub("_", fn)
    return fn


class ArtifactFileSystemStorageBinaryStream(ArtifactStorageBinaryStream):
    def __init__(self, concrete_path: pathlib.Path, reference_path: str):
        self._f = concrete_path.open("xb")
        self._reference_path = reference_path

    def write(self, data: bytes) -> int:
        return self._f.write(data)

    def close(self) -> None:
        self._f.close()

    def get_file_location_reference(self) -> str:
        return self._reference_path

    def __enter__(self) -> "ArtifactStorageBinaryStream":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._f.close()


class ArtifactFileSystemStorageTextStream(ArtifactStorageTextStream):
    def __init__(self, concrete_path: pathlib.Path, reference_path: str):
        self._f = concrete_path.open("xt")
        self._reference_path = reference_path

    def write(self, data: str) -> int:
        return self._f.write(data)

    def close(self) -> None:
        self._f.close()

    def get_file_location_reference(self) -> str:
        return self._reference_path

    def __enter__(self) -> "ArtifactStorageTextStream":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._f.close()


class ArtifactFileSystemStorage(ArtifactStorage):
    def __init__(self, root_path: pathlib.Path, folder_name: str):
        self._root_path = root_path
        self._folder_name = sanitize_filename(folder_name)

        if self._root_path.exists() and not self._root_path.is_dir():
            raise ValueError(f"{self._root_path} already exists and isn't a directory")

    def _get_stream(self, file_name: str, is_binary: bool) -> typing.Union[ArtifactStorageBinaryStream, ArtifactStorageTextStream]:
        if not isinstance(file_name, str):
            raise TypeError("file_name should be a str")

        out_dir = self._root_path / self._folder_name
        if not out_dir.exists():
            out_dir.mkdir(parents=True, exist_ok=True)

        file_name = sanitize_filename(file_name)
        if is_binary:
            return ArtifactFileSystemStorageBinaryStream(out_dir / file_name,
                                                         str(pathlib.Path(self._folder_name, file_name)))
        else:
            return ArtifactFileSystemStorageTextStream(out_dir / file_name,
                                                       str(pathlib.Path(self._folder_name, file_name)))

    def get_binary_stream(self, file_name: str) -> ArtifactStorageBinaryStream:
        return self._get_stream(file_name, is_binary=True)

    def get_text_stream(self, file_name: str) -> ArtifactStorageTextStream:
        return self._get_stream(file_name, is_binary=False)

