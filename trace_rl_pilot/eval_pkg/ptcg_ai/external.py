"""Isolated adapter for audited historical Kaggle submission directories."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from uuid import uuid4


class ExternalSubmissionAgent:
    """Load a submission without allowing its top-level package to collide."""

    def __init__(self, directory: str | os.PathLike[str], env: dict[str, str] | None = None):
        self.directory = Path(directory).resolve()
        self.deck = [int(line) for line in (self.directory / "deck.csv").read_text().splitlines() if line.strip()]
        if len(self.deck) != 60:
            raise ValueError(f"external deck must contain 60 cards: {self.directory}")
        self.errors = 0
        self._owned_module_names: set[str] = set()
        self.module = self._load(env or {})

    def _load(self, env: dict[str, str]) -> ModuleType:
        token = uuid4().hex
        package_name = f"_ptcg_external_{token}"
        main_name = f"{package_name}_main"
        self._owned_module_names.update((package_name, main_name))
        import_name = "agent" if (self.directory / "agent" / "__init__.py").exists() else "ptcg_ai"
        package_dir = self.directory / import_name
        package_spec = importlib.util.spec_from_file_location(
            package_name,
            package_dir / "__init__.py",
            submodule_search_locations=[str(package_dir)],
        )
        if package_spec is None or package_spec.loader is None:
            raise ImportError(f"cannot load external package: {package_dir}")
        package = importlib.util.module_from_spec(package_spec)
        sys.modules[package_name] = package
        package_spec.loader.exec_module(package)

        previous_modules = {
            name: module
            for name, module in sys.modules.items()
            if name == import_name or name.startswith(import_name + ".")
        }
        for name in previous_modules:
            sys.modules.pop(name, None)
        previous_env = dict(os.environ)
        previous_cwd = Path.cwd()
        sys.modules[import_name] = package
        os.environ.update({key: str(value) for key, value in env.items()})
        os.chdir(self.directory)
        try:
            main_spec = importlib.util.spec_from_file_location(main_name, self.directory / "main.py")
            if main_spec is None or main_spec.loader is None:
                raise ImportError(f"cannot load external main.py: {self.directory}")
            module = importlib.util.module_from_spec(main_spec)
            sys.modules[main_name] = module
            main_spec.loader.exec_module(module)
            return module
        finally:
            for name in list(sys.modules):
                if name == import_name or name.startswith(import_name + "."):
                    sys.modules.pop(name, None)
            sys.modules.update(previous_modules)
            # Submission imports may use setdefault or otherwise mutate process
            # configuration. Keep those values inside the loaded module only.
            os.environ.clear()
            os.environ.update(previous_env)
            os.chdir(previous_cwd)

    def close(self) -> None:
        """Release uniquely named modules after an isolated game completes."""
        prefixes = tuple(name + "." for name in self._owned_module_names)
        for name in list(sys.modules):
            if name in self._owned_module_names or name.startswith(prefixes):
                sys.modules.pop(name, None)
        self._owned_module_names.clear()

    def __del__(self):  # pragma: no cover - best-effort cleanup during shutdown
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def _fallback(obs: dict) -> list[int]:
        select = obs.get("select") or {}
        count = len(select.get("option", []))
        minimum = max(0, int(select.get("minCount", 0)))
        return list(range(min(minimum, count)))

    def __call__(self, obs: dict) -> list[int]:
        try:
            # Avoid the submission's cwd-sensitive deck lookup.
            if hasattr(self.module, "decide"):
                return self.module.decide(obs, self.deck)
            return self.module.agent(obs)
        except Exception:
            self.errors += 1
            return self._fallback(obs)
