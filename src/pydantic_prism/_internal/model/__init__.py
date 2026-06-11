"""The projection-building engine behind ``ScopedModel`` / ``Projection``.

The public ``Projection`` / ``ScopedModel`` classes live in
:mod:`pydantic_prism.model`; this package is their engine:
:mod:`collect` (marker collection → ``__field_scopes__`` / ``__refs__``),
:mod:`build` (the projection builder ``_project`` + naming + validator carry),
:mod:`schema` (scope-attached JSON schema), :mod:`bases` (carried-base checks),
:mod:`narrow` (round-trip narrowing). The classes lazy-import these helpers
(which import the classes at module level) to break the cycle. The public
classes are re-exported here (with ``as`` aliases) so the
``pydantic_prism._internal.model.X`` paths stay stable for intra-package use.
"""

from ...model import Projection as Projection
from ...model import ScopedModel as ScopedModel
from ...model import (
    _build_lock as _build_lock,  # pyright: ignore[reportPrivateUsage] — intra-package
)
from .build import _auto_name as _auto_name
from .build import _BuildContext as _BuildContext
from .build import _rewrite as _rewrite
from .collect import _variable_container as _variable_container
from .narrow import _narrow_value as _narrow_value
from .narrow import _validation_key as _validation_key

__all__ = ["Projection", "ScopedModel"]
