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

    assert_fresh(ScreenshotRef, "<signature>")   # startup drift guard

Layout: :mod:`_config` (load `[tool.pydantic-prism]`), :mod:`_discover` (find
the projection workset), :mod:`_render` (annotations/scopes/defaults → source),
:mod:`_generate` (assemble the stub + README), :mod:`_cli` (the ``prism``
command). Names re-exported here (with ``as`` aliases) keep the historical
``pydantic_prism._codegen.X`` import paths working.
"""

from ._cli import main as main
from ._config import CodegenError as CodegenError
from ._config import Config as Config
from ._config import ProjectionSpec as ProjectionSpec
from ._config import load_config as load_config
from ._discover import _projections_in as _projections_in
from ._discover import _reject_name_clashes as _reject_name_clashes
from ._generate import generate as generate
from ._generate import generate_readme as generate_readme
from ._render import _field_suffix as _field_suffix
from ._render import _import_lines as _import_lines
from ._render import _Imports as _Imports
from ._render import _render_annotation as _render_annotation
from ._render import _render_bare as _render_bare
from ._render import _render_literal as _render_literal
from ._render import _render_scope_expr as _render_scope_expr

__all__ = ["CodegenError", "Config", "ProjectionSpec", "generate", "main"]
