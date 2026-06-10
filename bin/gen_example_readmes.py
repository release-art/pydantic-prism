#!/usr/bin/env python
"""(Re)generate ``examples/<name>/README.md`` from each example's scoped models.

Each example under ``examples/`` is a standalone ``main.py`` defining
``ScopedModel`` subclasses. This loads each by path and renders a
GitHub-flavoured README (the same ``build_readme`` used by ``prism gen
--readme``): scope hierarchy + per-model projection + relationship Mermaid
diagrams, plus per-projection field tables.

Usage::

    python bin/gen_example_readmes.py            # write the READMEs
    python bin/gen_example_readmes.py --check     # exit 1 if any is stale (CI)
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def _load(main_py: Path) -> ModuleType:
    """Import an example's ``main.py`` under a unique synthetic module name."""
    name = f"_example_{main_py.parent.name}"
    spec = importlib.util.spec_from_file_location(name, main_py)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def readme_for(main_py: Path) -> str:
    """Render the README markdown for one example ``main.py``."""
    from pydantic_prism import ScopedModel
    from pydantic_prism._readme import build_readme

    module = _load(main_py)
    projections = [
        obj.scope(scope)
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, ScopedModel)
        and obj is not ScopedModel
        and obj.__module__ == module.__name__
        for scope in sorted(obj.scopes(), key=lambda s: s.__name__)
    ]
    return build_readme(projections)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify freshness instead of writing"
    )
    args = parser.parse_args(argv)

    stale: list[Path] = []
    for main_py in sorted(EXAMPLES.glob("*/main.py")):
        readme = readme_for(main_py)
        target = main_py.parent / "README.md"
        rel = target.relative_to(ROOT)
        if args.check:
            current = target.read_text(encoding="utf-8") if target.exists() else None
            if current != readme:
                stale.append(rel)
        else:
            target.write_text(readme, encoding="utf-8")
            print(f"wrote {rel}")

    if stale:
        for rel in stale:
            print(f"stale: {rel} — run `python bin/gen_example_readmes.py`", file=sys.stderr)
        return 1
    if args.check:
        print("example READMEs are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
