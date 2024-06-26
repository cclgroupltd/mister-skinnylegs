import pathlib
import typing
from collections.abc import Iterable
import importlib.util
from util.artifact_utils import ArtifactSpec


class PluginLoader:
    def __init__(self, plugin_path: typing.Optional[pathlib.Path] = None):
        self._plugin_path = plugin_path
        self._artifacts: dict[str, tuple[ArtifactSpec, pathlib.Path]] = {}
        self._load_plugins()

    @staticmethod
    def load_module_lazy(path: pathlib.Path):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        loader = importlib.util.LazyLoader(spec.loader)
        spec.loader = loader
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        return mod

    def _load_plugins(self):
        for py_file in self._plugin_path.glob("*_plugin.py"):
            mod = PluginLoader.load_module_lazy(py_file)
            mod_artifacts = getattr(mod, '__artifacts__', None)
            if mod_artifacts is None:
                continue  # no artifacts defined in this plugin

            for spec in mod_artifacts:
                if not isinstance(spec, ArtifactSpec):
                    raise TypeError(f"Unexpected type in __artifacts__ (got: {type(spec)}; expected PluginSpec)")
                if spec.name in self._artifacts:
                    raise KeyError(f"Duplicate plugin name ({spec.name} in {mod.__file__})")

                self._artifacts[spec.name] = spec, py_file

    @property
    def artifacts(self) -> Iterable[tuple[ArtifactSpec, pathlib.Path]]:
        yield from self._artifacts.values()

    def __getitem__(self, item: str) -> tuple[ArtifactSpec, pathlib.Path]:
        return self._artifacts[item]

    def __contains__(self, item):
        return item in self._artifacts

    def __len__(self):
        return len(self._artifacts)
