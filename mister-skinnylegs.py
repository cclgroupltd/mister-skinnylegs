import json
import sys
import pathlib
import typing
import collections.abc as colabc
from util.plugin_loader import PluginLoader
from util.artifact_utils import ArtifactResult, ArtifactSpec

from ccl_chromium_reader import ChromiumProfileFolder

PLUGIN_PATH = pathlib.Path(__file__).resolve().parent / pathlib.Path("plugins")

"""
TODO:

- Logging via a callback passed to the plugins
- Make everything async

"""


class MisterSkinnylegs:
    def __init__(
            self,
            plugin_path: pathlib.Path,
            profile_path: pathlib.Path,
            log_callback: typing.Optional[colabc.Callable[[str], None]]=None):
        self._plugin_loader = PluginLoader(plugin_path)

        if not profile_path.is_dir():
            raise NotADirectoryError(profile_path)

        self._profile_folder_path = profile_path

        self._log_callback = log_callback or MisterSkinnylegs.log_fallback

    def _run_artifact(self, spec: ArtifactSpec):
        with ChromiumProfileFolder(self._profile_folder_path) as profile:
            result = spec.method(profile, self._log_callback)
            return result

    def run_all(self):
        for spec, path in self.artifacts:
            result = self._run_artifact(spec)
            yield result

    def run_one(self, artifact_name: str):
        spec, path = self._plugin_loader[artifact_name]
        result = self._run_artifact(spec)
        return result

    @property
    def artifacts(self) -> colabc.Iterable[tuple[ArtifactSpec, pathlib.Path]]:
        yield from self._plugin_loader.artifacts

    @property
    def profile_folder(self) -> pathlib.Path:
        return self._profile_folder_path

    @staticmethod
    def log_fallback(message: str):
        print(f"Log:\t{message}")



def main(args):
    profile_input_path = pathlib.Path(args[0])
    mr_sl = MisterSkinnylegs(PLUGIN_PATH, profile_input_path)

    print("Working with profile folder: ")
    print(mr_sl.profile_folder)
    print()

    print("Plugins loaded:")
    print("===============")
    print(*(f"{spec.name}  -  {path.name}" for spec, path in mr_sl.artifacts), sep="\n")

    print()
    print("Running all processes")
    for result in mr_sl.run_all():
        print(json.dumps(result.result))

    print("Running Example artifact 2")
    print(json.dumps(mr_sl.run_one("Example artifact 2").result))


if __name__ == "__main__":
    main(sys.argv[1:])
