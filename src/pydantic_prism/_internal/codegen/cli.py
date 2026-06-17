"""The ``pydantic-prism`` CLI: ``gen`` / ``check`` / ``diagram`` subcommands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from .config import CodegenError, load_config
from .discover import (
    _prepend_sys_path,  # pyright: ignore[reportPrivateUsage] — intra-package
    _resolve,  # pyright: ignore[reportPrivateUsage] — intra-package
)
from .generate import generate, generate_readme

__all__ = ["main"]


# --- diagram subcommand ----------------------------------------------------


def _resolve_kind(path: str, want: type[Any], label: str) -> Any:
    obj = _resolve(path)
    if not (isinstance(obj, type) and issubclass(obj, want)):
        raise CodegenError(f"{path!r} is not a {label}")
    return obj


def _build_cli_diagram(kind: str, paths: Sequence[str], direction: str) -> Any:
    from ...diagram import projection_diagram, scope_diagram
    from ..model import ScopedModel
    from ..scopes import Scope

    # console scripts don't put the cwd on the path the way `python` does
    _prepend_sys_path(Path.cwd())
    if kind == "scope":
        scopes = [_resolve_kind(p, Scope, "Scope class") for p in paths]
        return scope_diagram(*scopes, direction=direction)
    if len(paths) != 1:
        raise CodegenError(f"`diagram {kind}` needs exactly one module:Model path")
    model = _resolve_kind(paths[0], ScopedModel, "ScopedModel subclass")
    if kind == "projection":
        return projection_diagram(model, direction=direction)
    return model.__prism__.refs.diagram(direction=direction)


def _render_diagram(diagram: Any, fmt: str) -> str:
    if fmt == "mermaid":
        return cast(str, diagram.to_mermaid())
    if fmt == "dot":
        return cast(str, diagram.to_dot())
    if fmt == "d2":
        return cast(str, diagram.to_d2())
    import json

    return json.dumps(diagram.as_dict(), indent=2) + "\n"


def _run_diagram(args: argparse.Namespace) -> int:
    try:
        diagram = _build_cli_diagram(args.kind, args.paths, args.direction)
    except CodegenError as exc:
        print(f"pydantic-prism: {exc}", file=sys.stderr)
        return 2
    rendered = _render_diagram(diagram, args.format)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
        print(f"pydantic-prism: wrote {args.format} diagram to {args.output}")
    else:
        print(rendered, end="")
    return 0


# --- flow subcommand -------------------------------------------------------


def _run_flow(args: argparse.Namespace) -> int:
    from ..model import ScopedModel

    # console scripts don't put the cwd on the path the way `python` does
    _prepend_sys_path(Path.cwd())
    try:
        model = _resolve_kind(args.path, ScopedModel, "ScopedModel subclass")
    except CodegenError as exc:
        print(f"pydantic-prism: {exc}", file=sys.stderr)
        return 2
    report = model.data_flow()
    if args.format == "mermaid":
        rendered = report.to_mermaid(direction=args.direction)
    else:
        import json

        rendered = json.dumps(report.as_dict(), indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
        print(f"pydantic-prism: wrote {args.format} flow report to {args.output}")
    else:
        print(rendered, end="")
    return 0


# --- gen / check -----------------------------------------------------------


def _stale(path: Path, expected: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    return existing != expected


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pydantic-prism",
        description="Generate static-typing stubs for prism projections.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("gen", "check"):
        p = sub.add_parser(command)
        p.add_argument(
            "--config", default="pyproject.toml", help="path to pyproject.toml"
        )
        p.add_argument(
            "--readme",
            default=None,
            help="also write/verify a GitHub README at PATH (overrides config)",
        )
    diagram_parser = sub.add_parser("diagram", help="render a structure diagram")
    diagram_parser.add_argument("kind", choices=("scope", "projection", "refs"))
    diagram_parser.add_argument(
        "paths", nargs="*", help="module:Name targets (scopes, or one model)"
    )
    diagram_parser.add_argument(
        "--format", choices=("mermaid", "dot", "d2", "json"), default="mermaid"
    )
    diagram_parser.add_argument("--output", default=None, help="write to FILE")
    diagram_parser.add_argument("--direction", choices=("TD", "LR"), default="TD")
    flow_parser = sub.add_parser(
        "flow", help="trace where classified (PII/Secret) data flows from a model"
    )
    flow_parser.add_argument("path", help="module:Model entry point")
    flow_parser.add_argument("--format", choices=("json", "mermaid"), default="json")
    flow_parser.add_argument("--output", default=None, help="write to FILE")
    flow_parser.add_argument("--direction", choices=("TD", "LR"), default="TD")
    args = parser.parse_args(argv)

    if args.command == "diagram":
        return _run_diagram(args)

    if args.command == "flow":
        return _run_flow(args)

    try:
        config = load_config(Path(args.config))
        text = generate(config)
        readme_path = Path(args.readme) if args.readme else config.readme
        readme_text = generate_readme(config) if readme_path is not None else None
    except (CodegenError, ValidationError, OSError) as exc:
        print(f"pydantic-prism: {exc}", file=sys.stderr)
        return 2

    if args.command == "gen":
        config.output.write_text(text, encoding="utf-8")
        count = text.count("\n    class ")  # one TYPE_CHECKING stub per projection
        print(f"pydantic-prism: wrote {count} projection stub(s) to {config.output}")
        if readme_path is not None and readme_text is not None:
            readme_path.write_text(readme_text, encoding="utf-8")
            print(f"pydantic-prism: wrote README to {readme_path}")
        return 0

    stale = "is out of date — run `pydantic-prism gen`"
    if _stale(config.output, text):
        print(f"pydantic-prism: {config.output} {stale}", file=sys.stderr)
        return 1
    if readme_text is not None and _stale(cast(Path, readme_path), readme_text):
        print(f"pydantic-prism: {readme_path} {stale}", file=sys.stderr)
        return 1
    print(f"pydantic-prism: {config.output} is up to date")
    return 0
