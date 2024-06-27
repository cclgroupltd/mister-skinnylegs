import json
import sys
import pathlib
import typing
import collections.abc as colabc
import asyncio
from util.plugin_loader import PluginLoader
from util.artifact_utils import ArtifactResult, ArtifactSpec
from util.fs_utils import sanitize_filename

from ccl_chromium_reader import ChromiumProfileFolder

__version__ = "0.0.2"
__description__ = "Library for reading Chrome/Chromium Cache (both blockfile and simple format)"
__contact__ = "Alex Caithness"

PLUGIN_PATH = pathlib.Path(__file__).resolve().parent / pathlib.Path("plugins")

BANNER = """
╔╦╗┬┌─┐┌┬┐┌─┐┬─┐            
║║║│└─┐ │ ├┤ ├┬┘            
╩ ╩┴└─┘ ┴ └─┘┴└─            
╔═╗┬┌─┬┌┐┌┌┐┌┬ ┬┬  ┌─┐┌─┐┌─┐
╚═╗├┴┐│││││││└┬┘│  ├┤ │ ┬└─┐
╚═╝┴ ┴┴┘└┘┘└┘ ┴ ┴─┘└─┘└─┘└─┘
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

    async def _run_artifact(self, spec: ArtifactSpec):
        with ChromiumProfileFolder(self._profile_folder_path) as profile:
            result = spec.function(profile, self._log_callback)
            return spec, {
                "artifact_service": spec.service,
                "artifact_name": spec.name,
                "artifact_version": spec.version,
                "artifact_description": spec.description,
                "result": result.result}

    async def run_all(self):
        tasks = (self._run_artifact(spec) for spec, path in self.artifacts)
        for coro in asyncio.as_completed(tasks):
            yield await coro

    async def run_one(self, artifact_name: str):
        spec, path = self._plugin_loader[artifact_name]
        result = self._run_artifact(spec)
        return spec, result

    @property
    def artifacts(self) -> colabc.Iterable[tuple[ArtifactSpec, pathlib.Path]]:
        yield from self._plugin_loader.artifacts

    @property
    def profile_folder(self) -> pathlib.Path:
        return self._profile_folder_path

    @staticmethod
    def log_fallback(message: str):
        print(f"Log:\t{message}")


async def main(args):
    profile_input_path = pathlib.Path(args[0])
    report_out_folder_path = pathlib.Path(args[1])

    print(BANNER)

    mr_sl = MisterSkinnylegs(PLUGIN_PATH, profile_input_path)

    if report_out_folder_path.exists():
        raise FileExistsError(f"Output folder {report_out_folder_path} already exists")

    report_out_folder_path.mkdir(parents=True)

    print(f"Working with profile folder: {mr_sl.profile_folder}")
    print()

    print("Plugins loaded:")
    print("===============")
    print(*(f"{spec.name}  -  {path.name}" for spec, path in mr_sl.artifacts), sep="\n")

    print()

    # TODO replace fallback logging.

    async for spec, result in mr_sl.run_all():
        MisterSkinnylegs.log_fallback(f"Results acquired for {spec.name}")
        if not result["result"]:
            MisterSkinnylegs.log_fallback(f"{spec.name} had not results, skipping")
            continue

        out_dir_path = report_out_folder_path / sanitize_filename(spec.service)
        out_dir_path.mkdir(exist_ok=True)
        out_file_path = out_dir_path / (sanitize_filename(spec.name) + ".json")

        MisterSkinnylegs.log_fallback(f"Generating output at {out_file_path}")

        with out_file_path.open("xt", encoding="utf-8") as out:
            json.dump(result, out)



if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
