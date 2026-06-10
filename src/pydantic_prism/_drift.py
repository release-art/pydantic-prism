"""Drift detection for ``prism gen``-generated projection stubs.

A generated stub records, per projection, a short signature of the projection's
shape at generation time. At import of the generated module (application
startup) :func:`assert_fresh` recomputes the signature from the live model and
compares; a mismatch means the model changed but the stub was not regenerated,
so the static types it declares no longer hold. The same function backs the
non-importing ``prism check`` CI gate.

The signature covers each projection's *own* direct fields (name, annotation,
required-ness) plus its carried bases. That is sufficient even for nested
projections: every projection a stub references is itself generated and
asserted, so a change to a nested model is caught by *that* projection's own
signature — not hidden behind the outer one.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from .errors import StaleProjectionStubError

if TYPE_CHECKING:
    from ._model import Projection

__all__ = ["assert_fresh", "projection_signature"]


def projection_signature(projection: type[Projection]) -> str:
    """A short, stable hash of a projection class's externally visible shape.

    Deterministic across interpreter runs for an unchanged model definition:
    it reads field names, their annotation's ``str`` (stable — module-qualified
    type names, including nested projections by class name), whether each field
    is required, and the carried-base names.
    """
    fields = [
        (name, str(info.annotation), info.is_required())
        for name, info in projection.model_fields.items()
    ]
    bases = tuple(base.__name__ for base in projection.__prism_bases__)
    payload = repr((projection.__name__, fields, bases))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def assert_fresh(projection: type[Projection], expected: str) -> None:
    """Raise :class:`StaleProjectionStubError` if ``projection`` has drifted.

    Called once per generated projection at import of the generated module.
    ``expected`` is the signature recorded by ``prism gen``.
    """
    actual = projection_signature(projection)
    if actual != expected:
        source = projection.__prism_source__
        raise StaleProjectionStubError(
            f"generated stub for {projection.__name__} (projection of "
            f"{source.__module__}.{source.__qualname__}) is stale: recorded "
            f"signature {expected!r} != current {actual!r}. The model changed "
            f"since the stub was generated — re-run `prism gen`."
        )
