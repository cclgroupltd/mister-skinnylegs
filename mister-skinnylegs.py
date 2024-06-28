import csv
import datetime
import json
import sys
import pathlib
import typing
import collections.abc as colabc
import asyncio
from util.plugin_loader import PluginLoader
from util.artifact_utils import ArtifactResult, ArtifactSpec, ReportPresentation, LogFunction, ArtifactStorage
from util.fs_utils import sanitize_filename, ArtifactFileSystemStorage

from ccl_chromium_reader import ChromiumProfileFolder

__version__ = "0.0.4"
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
    """
    Mister Skinnylegs is a plugin framework for website/web app artifacts stored by a browser.
    """
    def __init__(
            self,
            plugin_path: pathlib.Path,
            profile_path: pathlib.Path,
            storage_maker_func: colabc.Callable[[ArtifactSpec], ArtifactStorage],
            log_callback: typing.Optional[LogFunction]=None,
            ):
        """
        Constructor

        :param plugin_path: path to the folder of plugins .
        :param profile_path: path to the (Chrome/Chromium) browser profile folder.
        :param storage_maker_func: a function which takes an ArtifactSpec object and returns an object that
               implements the ArtifactStorage interface.
        :param log_callback: a callback function for logging. Should be a function that takes a single string
               argument which is the message to be logged.
        """
        self._plugin_loader = PluginLoader(plugin_path)

        if not profile_path.is_dir():
            raise NotADirectoryError(profile_path)

        self._profile_folder_path = profile_path
        self._storage_maker_func = storage_maker_func
        self._log_callback = log_callback or MisterSkinnylegs.log_fallback

    async def _run_artifact(self, spec: ArtifactSpec):
        with ChromiumProfileFolder(self._profile_folder_path) as profile:
            result = spec.function(profile, self._log_callback, self._storage_maker_func(spec))
            return spec, {
                "artifact_service": spec.service,
                "artifact_name": spec.name,
                "artifact_version": spec.version,
                "artifact_description": spec.description,
                "result": result.result}

    async def run_all(self):
        """
        Async generator function that runs all loaded plugins against the profile folder provided to the constructor
        """
        tasks = (self._run_artifact(spec) for spec, path in self.artifacts)
        for coro in asyncio.as_completed(tasks):
            yield await coro

    async def run_one(self, artifact_name: str):
        """
        Asynchronously runs the artifact with the given name
        :param artifact_name:
        """
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


class SimpleLog:
    """
    A simple log class designed to be passed around.
    """

    def __init__(self, out_path: pathlib.Path):
        """
        Constructor. Creates a log file at the given path. Fails if the file already exists.

        :param out_path: File path for the log file. Must not already exist.
        """
        self._f = out_path.open("xt", encoding="utf-8")

    def log_message(self, message: str) -> None:
        """
        Logs a message. The logged message includes a timestamp and the calling module + function

        :param message: The message to log, as a string.
        """
        caller_name = f"{sys._getframemodulename(1)}.{sys._getframe(1).f_code.co_name}"
        formatted_message = f"{datetime.datetime.now()}\t{caller_name}\t{message.replace('\n', '\n\t')}"
        self._f.write(formatted_message)
        self._f.write("\n")

        print(formatted_message.encode(sys.stdout.encoding, "replace").decode(sys.stdout.encoding))

    def close(self) -> None:
        """
        Close the log file.
        """
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def write_csv(csv_out: typing.TextIO, result: list):
    fields = []
    for rec in result:
        for k in rec.keys():
            if k not in fields:
                fields.append(k)

    writer = csv.DictWriter(csv_out, fields)
    writer.writeheader()
    writer.writerows(result)


async def main(args):
    profile_input_path = pathlib.Path(args[0])
    report_out_folder_path = pathlib.Path(args[1])

    print(BANNER)

    if not profile_input_path.is_dir():
        raise NotADirectoryError(f"Profile folder {profile_input_path} does not exist or is not a directory")

    if report_out_folder_path.exists():
        raise FileExistsError(f"Output folder {report_out_folder_path} already exists")

    report_out_folder_path.mkdir(parents=True)
    log_file = SimpleLog(report_out_folder_path / f"log_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")
    log = log_file.log_message

    mr_sl = MisterSkinnylegs(
        PLUGIN_PATH,
        profile_input_path,
        lambda s: ArtifactFileSystemStorage(
            report_out_folder_path / sanitize_filename(spec.service),
            sanitize_filename(s.name) + "_files"),
        log_callback=log)

    log(f"Mister Skinnylegs v{__version__} is on the go!")
    log(f"Working with profile folder: {mr_sl.profile_folder}")
    log("")

    log("Plugins loaded:")
    log("===============")
    for spec, path in mr_sl.artifacts:
        log(f"{spec.name}  -  {path.name}")

    log("")
    log("Processing starting...")

    async for spec, result in mr_sl.run_all():
        log(f"Results acquired for {spec.name}")
        if not result["result"]:
            log(f"{spec.name} had not results, skipping")
            continue

        out_dir_path = report_out_folder_path / sanitize_filename(spec.service)
        out_dir_path.mkdir(exist_ok=True)
        out_file_path = out_dir_path / (sanitize_filename(spec.name) + ".json")

        log(f"Generating output at {out_file_path}")

        with out_file_path.open("xt", encoding="utf-8") as out:
            json.dump(result, out)
        if spec.presentation == ReportPresentation.table:
            csv_out_path = out_file_path.with_suffix(".csv")
            log(f"Generating csv output at {csv_out_path}")
            with csv_out_path.open("xt", encoding="utf-8", newline="") as csv_out:
                write_csv(csv_out, result["result"])

    log("")
    log("Processes complete")
    log("Mister Skinnylegs is going home...")

    log_file.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"USAGE: {pathlib.Path(sys.argv[0]).name} <profile folder path> <output folder path>")
        exit(1)
    asyncio.run(main(sys.argv[1:]))
