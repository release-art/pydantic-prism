"""ScopedModel, Projection, and the projection builder.

Layout: :mod:`_classes` (the ``Projection`` / ``ScopedModel`` classes),
:mod:`_collect` (marker collection → ``__field_scopes__`` / ``__refs__``),
:mod:`_build` (the projection builder ``_project`` + naming + validator carry),
:mod:`_schema` (scope-attached JSON schema), :mod:`_bases` (carried-base checks),
:mod:`_narrow` (round-trip narrowing). The classes lazy-import the helpers (which
import the classes at module level) to break the cycle. Names re-exported here
(with ``as`` aliases) keep the historical ``pydantic_prism._model.X`` paths.
"""

from ._build import _auto_name as _auto_name
from ._build import _BuildContext as _BuildContext
from ._build import _rewrite as _rewrite
from ._classes import Projection as Projection
from ._classes import ScopedModel as ScopedModel
from ._classes import (
    _build_lock as _build_lock,  # pyright: ignore[reportPrivateUsage] — intra-package
)
from ._collect import _variable_container as _variable_container
from ._narrow import _narrow_value as _narrow_value
from ._narrow import _validation_key as _validation_key

__all__ = ["Projection", "ScopedModel"]
