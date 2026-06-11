"""``prism gen`` / ``prism check`` — generate static-typing stubs for projections.

Static type checkers (pyright/Pylance — and thus VSCode — plus mypy) cannot see
the fields of ``Model.scope(...)``: scope membership lives in ``Annotated``
metadata and the selection runs the scope algebra at runtime. Pyright has no
third-party plugin API, so the only *universal* fix is ordinary type
declarations every tool already reads. This package generates them.

For each projection it emits, into one module::

    if TYPE_CHECKING:
        class ScreenshotRef(Projection):     # the checker reads this
            id: UUID
            timestamp: datetime
    else:
        ScreenshotRef = Screenshot.scope(Ref)   # the genuine cached projection

The runtime alias is recomputed live every import, so it is never stale; drift
between the static stub and the model is caught by ``prism check`` (which
regenerates the module and byte-diffs it) as a CI gate.

Layout: :mod:`config` (load `[tool.pydantic-prism]`), :mod:`discover` (find
the projection workset), :mod:`render` (annotations/scopes/defaults → source),
:mod:`generate` (assemble the stub + README), :mod:`cli` (the ``prism``
command). Names re-exported here (with ``as`` aliases) keep the
``pydantic_prism._internal.codegen.X`` import paths stable.
"""

from .cli import main as main
from .config import CodegenError as CodegenError
from .config import Config as Config
from .config import ProjectionSpec as ProjectionSpec
from .config import load_config as load_config
from .discover import _projections_in as _projections_in
from .discover import _reject_name_clashes as _reject_name_clashes
from .generate import generate as generate
from .generate import generate_readme as generate_readme
from .render import _field_suffix as _field_suffix
from .render import _import_lines as _import_lines
from .render import _Imports as _Imports
from .render import _render_annotation as _render_annotation
from .render import _render_bare as _render_bare
from .render import _render_literal as _render_literal
from .render import _render_scope_expr as _render_scope_expr

__all__ = ["CodegenError", "Config", "ProjectionSpec", "generate", "main"]
