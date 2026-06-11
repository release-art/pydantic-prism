"""``[tool.pydantic-prism]`` configuration loading."""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

__all__ = ["CodegenError", "Config", "ProjectionSpec", "load_config"]


class CodegenError(Exception):
    """A stub-generation request could not be fulfilled (bad config or input)."""


@dataclass(frozen=True, slots=True)
class ProjectionSpec:
    """One opt-in projection beyond a model's per-atom defaults.

    ``model`` and each ``scopes`` entry are ``"package.module:Name"`` paths; the
    scopes union together (equivalent to ``.scope(A | B)``).
    """

    model: str
    scopes: tuple[str, ...]
    name: str | None = None


@dataclass(frozen=True, slots=True)
class Config:
    """Resolved ``[tool.pydantic-prism]`` configuration."""

    output: Path
    modules: tuple[str, ...]
    projections: tuple[ProjectionSpec, ...]
    root: Path
    readme: Path | None = None


def load_config(pyproject: Path) -> Config:
    """Read ``[tool.pydantic-prism]`` from a ``pyproject.toml``."""
    with pyproject.open("rb") as handle:
        data = tomllib.load(handle)
    table = data.get("tool", {}).get("pydantic-prism")
    if not isinstance(table, dict):
        raise CodegenError(
            f"{pyproject}: no [tool.pydantic-prism] table; add one with an "
            f"`output` path and `modules` to scan"
        )
    table = cast(dict[str, Any], table)
    output = table.get("output")
    if not isinstance(output, str):
        raise CodegenError(
            f"{pyproject}: [tool.pydantic-prism] needs a string `output` path"
        )
    modules = tuple(cast(Sequence[str], table.get("modules", [])))
    raw_projections = cast(Sequence[Any], table.get("projections", []))
    projections = tuple(_parse_spec(entry, pyproject) for entry in raw_projections)
    if not modules and not projections:
        raise CodegenError(
            f"{pyproject}: [tool.pydantic-prism] selects nothing — set `modules` "
            f"and/or `projections`"
        )
    readme = table.get("readme")
    if readme is not None and not isinstance(readme, str):
        raise CodegenError(
            f"{pyproject}: [tool.pydantic-prism] `readme` must be a string path"
        )
    root = pyproject.resolve().parent
    return Config(
        output=root / output,
        modules=modules,
        projections=projections,
        root=root,
        readme=(root / readme) if isinstance(readme, str) else None,
    )


def _parse_spec(entry: Any, pyproject: Path) -> ProjectionSpec:
    if not isinstance(entry, dict):
        raise CodegenError(
            f"{pyproject}: each [[tool.pydantic-prism.projections]] "
            f"entry must be a table, got {entry!r}"
        )
    entry = cast(dict[str, Any], entry)
    model = entry.get("model")
    scopes = entry.get("scopes")
    name = entry.get("name")
    if not isinstance(model, str):
        raise CodegenError(f"{pyproject}: a projections entry needs a string `model`")
    scope_list = cast(list[Any], scopes) if isinstance(scopes, list) else []
    if not scope_list or not all(isinstance(s, str) for s in scope_list):
        raise CodegenError(
            f"{pyproject}: projections entry for {model!r} needs a non-empty "
            f"`scopes` list of 'module:Name' strings"
        )
    if name is not None and not isinstance(name, str):
        raise CodegenError(
            f"{pyproject}: projections `name` for {model!r} must be a string"
        )
    return ProjectionSpec(
        model=model, scopes=tuple(cast(list[str], scope_list)), name=name
    )
