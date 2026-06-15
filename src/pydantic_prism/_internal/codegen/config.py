"""``[tool.pydantic-prism]`` configuration loading.

The raw TOML table is parsed and normalised through pydantic models
(:class:`_RawConfig` / :class:`_RawProjection`) — prism depends on pydantic,
so there is no reason to hand-roll the shape checks. Field-shape problems
surface as a native ``pydantic.ValidationError``; the two conditions pydantic
cannot phrase helpfully (the table is absent entirely, or it selects nothing
to generate) stay as :class:`CodegenError`.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class _RawProjection(BaseModel):
    """A ``[[tool.pydantic-prism.projections]]`` table, as written in TOML."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model: str
    scopes: Annotated[tuple[str, ...], Field(min_length=1)]
    name: str | None = None


class _RawConfig(BaseModel):
    """The ``[tool.pydantic-prism]`` table, as written in TOML."""

    model_config = ConfigDict(extra="forbid")

    output: str
    modules: tuple[str, ...] = ()
    projections: tuple[_RawProjection, ...] = ()
    readme: str | None = None

    @model_validator(mode="after")
    def _selects_something(self) -> _RawConfig:
        if not self.modules and not self.projections:
            raise ValueError(
                "[tool.pydantic-prism] selects nothing — set `modules` "
                "and/or `projections`"
            )
        return self


def load_config(pyproject: Path) -> Config:
    """Read ``[tool.pydantic-prism]`` from a ``pyproject.toml``.

    Raises :class:`CodegenError` if the table is missing, and
    ``pydantic.ValidationError`` if its contents are malformed.
    """
    with pyproject.open("rb") as handle:
        data: dict[str, Any] = tomllib.load(handle)
    table = data.get("tool", {}).get("pydantic-prism")
    if table is None:
        raise CodegenError(
            f"{pyproject}: no [tool.pydantic-prism] table; add one with an "
            f"`output` path and `modules` to scan"
        )
    raw = _RawConfig.model_validate(table)
    root = pyproject.resolve().parent
    return Config(
        output=root / raw.output,
        modules=raw.modules,
        projections=tuple(
            ProjectionSpec(model=spec.model, scopes=spec.scopes, name=spec.name)
            for spec in raw.projections
        ),
        root=root,
        readme=(root / raw.readme) if raw.readme is not None else None,
    )
