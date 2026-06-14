"""Keep the Markdown docs honest.

Two guards so the docs can't silently rot:

* every relative link in README / ROADMAP / docs/ resolves to a real file, and
* the fenced ``python`` blocks of the self-contained docs actually run against
  the current code (each file executed as one concatenated script).

Docs that need a running server / database (the FastAPI and ORM guides) or that
import a *generated* module (the codegen guide) are covered by their own example
tests and are not executed here.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
_PY_BLOCK = re.compile(r"```python\n(.*?)```", re.DOTALL)


def _markdown_files() -> list[Path]:
    # The ADR archive under docs/decisions/ is preserved verbatim; its internal
    # links point at notes that were intentionally removed, so it is not part of
    # the navigable tree this guard checks.
    docs = [
        p
        for p in sorted(_ROOT.glob("docs/**/*.md"))
        if not re.match(r"design-round-\d+\.md|api-decisions\.md", p.name)
    ]
    return [_ROOT / "README.md", _ROOT / "ROADMAP.md", *docs]


def _doc_id(path: Path) -> str:
    return str(path.relative_to(_ROOT))


@pytest.mark.parametrize("md", _markdown_files(), ids=_doc_id)
def test_relative_links_resolve(md: Path) -> None:
    for target in _LINK.findall(md.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = target.split("#", 1)[0]  # drop any anchor; pure #anchors handled above
        resolved = (md.parent / path).resolve()
        assert resolved.exists(), f"{md.relative_to(_ROOT)} links to missing {target!r}"


# Docs whose python blocks concatenate into one runnable script.
_RUNNABLE = [
    "docs/tutorial/first-scoped-model.md",
    "docs/how-to/redact-pii.md",
    "docs/how-to/trace-data-flow.md",
    "docs/how-to/partial-update.md",
    "docs/how-to/prevent-mass-assignment.md",
    "docs/how-to/carry-a-custom-base.md",
    "docs/how-to/vary-schema-per-scope.md",
    "docs/how-to/retype-a-field-per-scope.md",
    "docs/how-to/keep-behavior-on-projections.md",
    "docs/how-to/derive-llm-tool-schema.md",
    "docs/how-to/use-with-pydantic-ai.md",
    "docs/how-to/export-diagrams.md",
    "docs/how-to/use-with-fastapi.md",
]


@pytest.mark.parametrize("rel", _RUNNABLE)
def test_doc_python_blocks_execute(rel: str) -> None:
    source = (_ROOT / rel).read_text(encoding="utf-8")
    blocks = _PY_BLOCK.findall(source)
    assert blocks, f"{rel} has no python blocks to run"
    script = "\n".join(blocks)
    # Run inside a real, registered module so pydantic can resolve the models'
    # annotations against the namespace the way it would in an ordinary import.
    mod_name = "docs_exec_" + re.sub(r"\W", "_", rel)
    module = ModuleType(mod_name)
    sys.modules[mod_name] = module
    try:
        exec(compile(script, rel, "exec"), module.__dict__)  # noqa: S102 — our own docs
    finally:
        del sys.modules[mod_name]
