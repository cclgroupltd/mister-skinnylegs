"""
Copyright (c) 2024 CCL Solutions Group

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import csv
import datetime
import enum
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
from ccl_mozilla_reader import MozillaProfileFolder

__version__ = "0.0.12"
__description__ = "an open plugin framework for parsing website/webapp artifacts in browser data"
__contact__ = "Alex Caithness"

PLUGIN_PATH = pathlib.Path(__file__).resolve().parent / pathlib.Path("plugins")

BANNER = """
╔╦╗┬┌─┐┌┬┐┌─┐┬─┐            
║║║│└─┐ │ ├┤ ├┬┘            
╩ ╩┴└─┘ ┴ └─┘┴└─            
╔═╗┬┌─┬┌┐┌┌┐┌┬ ┬┬  ┌─┐┌─┐┌─┐
╚═╗├┴┐│││││││└┬┘│  ├┤ │ ┬└─┐
╚═╝┴ ┴┴┘└┘┘└┘ ┴ ┴─┘└─┘└─┘└─┘
by CCL Forensics Ltd.
For updates, support, and feature requests:
https://github.com/cclgroupltd/mister-skinnylegs
"""


class ExtendedEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        return super().default(obj)


class BrowserType(enum.Enum):
    chromium = 1
    mozilla = 2


class MisterSkinnylegs:
    """
    Mister Skinnylegs is a plugin framework for website/web app artifacts stored by a browser.
    """
    def __init__(
            self,
            plugin_path: pathlib.Path,
            profile_path: pathlib.Path,
            browser_type: BrowserType,
            storage_maker_func: colabc.Callable[[ArtifactSpec], ArtifactStorage],
            cache_folder: typing.Optional[pathlib.Path]=None,
            log_callback: typing.Optional[LogFunction]=None,
            ):
        """
        Constructor

        :param plugin_path: path to the folder of plugins .
        :param profile_path: path to the (Chrome/Chromium) browser profile folder.
        :param browser_type: the browser type for this data
        :param storage_maker_func: a function which takes an ArtifactSpec object and returns an object that
               implements the ArtifactStorage interface.
        :param cache_folder:
        :param log_callback: a callback function for logging. Should be a function that takes a single string
               argument which is the message to be logged.
        """
        self._plugin_loader = PluginLoader(plugin_path)

        if not profile_path.is_dir():
            raise NotADirectoryError(profile_path)

        if cache_folder is not None and not cache_folder.is_dir():
            raise NotADirectoryError(cache_folder)

        self._profile_folder_path = profile_path
        self._browser_type = browser_type
        self._cache_folder_path = cache_folder
        self._storage_maker_func = storage_maker_func
        self._log_callback = log_callback or MisterSkinnylegs.log_fallback

        match self._browser_type:
            case BrowserType.chromium:
                self._make_profile = lambda: ChromiumProfileFolder(
                    self._profile_folder_path, cache_folder=self._cache_folder_path)
            case BrowserType.mozilla:
                self._make_profile = lambda: MozillaProfileFolder(self._profile_folder_path, self._cache_folder_path)
            case _:
                raise NotImplementedError(f"Browser type {self._browser_type} not supported")

    async def _run_artifact(self, spec: ArtifactSpec):
        # with ChromiumProfileFolder(self._profile_folder_path, cache_folder=self._cache_folder_path) as profile:
        with self._make_profile() as profile:
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

    @property
    def browser_type(self):
        return self._browser_type

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


async def main(
        profile_input_folder: pathlib.Path,
        report_output_folder: pathlib.Path,
        browser_type: BrowserType,
        cache_folder: typing.Optional[pathlib.Path]=None):
    print(BANNER)

    if not profile_input_folder.is_dir():
        raise NotADirectoryError(f"Profile folder {profile_input_folder} does not exist or is not a directory")

    if report_output_folder.exists():
        raise FileExistsError(f"Output folder {report_output_folder} already exists")

    # checks for specific browser types
    if browser_type == BrowserType.mozilla:
        if cache_folder is None or not cache_folder.is_dir():
            raise NotADirectoryError("Processing Mozilla requires a specific cache folder")

    report_output_folder.mkdir(parents=True)
    log_file = SimpleLog(report_output_folder / f"log_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")
    log = log_file.log_message

    mr_sl = MisterSkinnylegs(
        PLUGIN_PATH,
        profile_input_folder,
        browser_type,
        lambda s: ArtifactFileSystemStorage(
            report_output_folder / sanitize_filename(s.service),
            sanitize_filename(s.name) + "_files"),
        cache_folder=cache_folder,
        log_callback=log)

    log(f"Mister Skinnylegs v{__version__} is on the go!")
    log(f"Working with profile folder: {mr_sl.profile_folder}")
    log("")

    log("Plugins loaded:")
    log("===============")
    for spec, path in mr_sl.artifacts:
        log(f"{spec.name}\tv{spec.version} -\t{path.name}")

    log("")
    log("Processing starting...")

    async for spec, result in mr_sl.run_all():
        log(f"Results acquired for {spec.name}")
        if not result["result"]:
            log(f"{spec.name} had no results, skipping")
            continue

        out_dir_path = report_output_folder / sanitize_filename(spec.service)
        out_dir_path.mkdir(exist_ok=True)
        out_file_path = out_dir_path / (sanitize_filename(spec.name) + ".json")

        log(f"Generating output at {out_file_path}")

        with out_file_path.open("xt", encoding="utf-8") as out:
            json.dump(result, out, cls=ExtendedEncoder)
        if spec.presentation == ReportPresentation.table:
            csv_out_path = out_file_path.with_suffix(".csv")
            log(f"Generating csv output at {csv_out_path}")
            with csv_out_path.open("xt", encoding="utf-8", newline="") as csv_out:
                write_csv(csv_out, result["result"])

    log("")
    log("Processing complete")
    log("Mister Skinnylegs is going home...")

    log_file.close()
    print()
    print()


def list_plugins():
    loader = PluginLoader(PLUGIN_PATH)
    for artifact, location in loader.artifacts:
        print(f"- {location.name}\t{artifact.service}\t{artifact.name}\t{artifact.version}")
        print("\n".join(f"\t{desc_line}" for desc_line in artifact.description.splitlines(keepends=False)))
        if artifact.citation:
            print("\n".join(f"\t{cite_line}" for cite_line in artifact.citation.splitlines(keepends=False)))


def table_plugins():
    loader = PluginLoader(PLUGIN_PATH)
    print("| Plugin File | Service | Artifact | Version | Description |")
    print("| ----------- | ------- | -------- | ------- | ----------- |")
    for artifact, location in loader.artifacts:
        print("| ", end="")
        print(" | ".join([
            location.name,
            artifact.service,
            artifact.name,
            artifact.version,
            "<br>".join(artifact.description.splitlines(keepends=False))]), end="")
        print(" |")


if __name__ == "__main__":
    import argparse
    arg_parser = argparse.ArgumentParser(
        prog="mister-skinnylegs",
        description="mister-skinnylegs is an open plugin framework for parsing website/webapp artifacts in browser "
                    "data. This command-line interface runs the plugins in the 'plugins' folder against the provided "
                    "profile folder.",
        exit_on_error=False
    )
    arg_parser.add_argument(
        "-l", "--list_plugins",
        action="store_true",
        dest="list_plugins",
        help="list plugins and quit"
    )
    arg_parser.add_argument(
        "-t", "--table_list_plugins",
        action="store_true",
        dest="table_list_plugins",
        help="list plugins as a markdown table and quit"
    )

    profile_folder_arg_names = ["--profile-folder", "-p"]
    profile_folder_arg_args = {"type": pathlib.Path, "dest": "profile_folder"}
    output_folder_arg_names = ["--output-folder", "-o"]
    output_folder_arg_args = {
        "type": pathlib.Path, "dest": "output_folder",
        "help": "output folder for processed data - should not already exist"}
    cache_folder_arg_names = ["--cache-folder", "-c"]
    cache_folder_arg_args = {"action": "store", "dest": "cache_folder", "type": pathlib.Path}

    sub_parsers = arg_parser.add_subparsers(required=True, help="browsers", dest="browser_type")
    chrome_parser = sub_parsers.add_parser("chromium")
    mozilla_parser = sub_parsers.add_parser("mozilla")

    chrome_parser.add_argument(
        *profile_folder_arg_names,
        required=True,
        help="the path to the chrom(e|ium) profile folder",
        **profile_folder_arg_args)
    chrome_parser.add_argument(
        *cache_folder_arg_names,
        required=False,
        default=None,
        help="optional path to the cache folder, if it is not found directly within the profile folder (e.g.,as is the "
             "case on Android)",
        **cache_folder_arg_args
    )
    chrome_parser.add_argument(
        *output_folder_arg_names,
        required=True,
        **output_folder_arg_args
    )
    mozilla_parser.add_argument(
        *profile_folder_arg_names,
        required=True,
        help="the path to the mozilla profile folder",
        **profile_folder_arg_args
    )
    mozilla_parser.add_argument(
        *cache_folder_arg_names,
        required=True,
        help="path to the cache folder (usually named 'cache2'); on most platforms this is stored outside of the "
             "main profile folder.",
        **cache_folder_arg_args
    )
    mozilla_parser.add_argument(
        *output_folder_arg_names,
        required=True,
        **output_folder_arg_args
    )

    if "-l" in sys.argv or "--list_plugins" in sys.argv:
        print(BANNER)
        list_plugins()
        exit(0)

    if "-t" in sys.argv or "--table_list_plugins" in sys.argv:
        print(BANNER)
        table_plugins()
        exit(0)

    args = arg_parser.parse_args()
    print(args)

    asyncio.run(
        main(args.profile_folder, args.output_folder, BrowserType[args.browser_type], cache_folder=args.cache_folder))
