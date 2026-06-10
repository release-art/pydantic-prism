"""ScopedModel, Projection, and the projection builder.

Layout: :mod:`classes` (the ``Projection`` / ``ScopedModel`` classes),
:mod:`collect` (marker collection → ``__field_scopes__`` / ``__refs__``),
:mod:`build` (the projection builder ``_project`` + naming + validator carry),
:mod:`schema` (scope-attached JSON schema), :mod:`bases` (carried-base checks),
:mod:`narrow` (round-trip narrowing). The classes lazy-import the helpers (which
import the classes at module level) to break the cycle. Names re-exported here
(with ``as`` aliases) keep the ``pydantic_prism._internal.model.X`` paths stable.
"""

from .build import _auto_name as _auto_name
from .build import _BuildContext as _BuildContext
from .build import _rewrite as _rewrite
from .classes import Projection as Projection
from .classes import ScopedModel as ScopedModel
from .classes import (
    _build_lock as _build_lock,  # pyright: ignore[reportPrivateUsage] — intra-package
)
from .collect import _variable_container as _variable_container
from .narrow import _narrow_value as _narrow_value
from .narrow import _validation_key as _validation_key

__all__ = ["Projection", "ScopedModel"]
