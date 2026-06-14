"""Targeted tests for internal helpers and reflection/edge branches."""

import threading
from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, Field

from pydantic_prism import (
    RefResolutionError,
    RefShape,
    Scope,
    ScopedModel,
    backref,
    ref,
    scoped,
)
from pydantic_prism._internal.model import (
    _build_lock,
    _narrow_value,
    _rewrite,
    _variable_container,
)
from pydantic_prism._internal.scopes import as_expr, intersect_all, union_all
from pydantic_prism.refs import shape_of


class Public(Scope): ...


class Internal(Public): ...


class Thing(ScopedModel):
    id: Annotated[UUID, scoped(Public)]


class DanglingTarget(ScopedModel):
    id: Annotated[UUID, scoped(Public)]
    other_id: Annotated[UUID, ref("NoSuchModel"), scoped(Public)]


# --- scope expression internals -------------------------------------------


def test_reflected_operators_on_foreign_operands() -> None:
    expr = as_expr(Public)
    with pytest.raises(TypeError):
        _ = 1 | expr  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = 1 & expr  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = 1 - expr  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = 1 | Public  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = 1 & Public  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = 1 - Public  # type: ignore[operator]


def test_union_and_intersection_require_operands() -> None:
    with pytest.raises(TypeError):
        union_all([])
    with pytest.raises(TypeError):
        intersect_all([])


def test_intersection_of_equal_atoms_collapses() -> None:
    assert (Public & Public) == as_expr(Public)


def test_nested_expressions_sort_canonically() -> None:
    # _Union.sort_key is exercised when unions are operands of a wider node
    left = (Public | Internal) & Public
    right = Public & (Internal | Public)
    assert left == right


# --- shape inference --------------------------------------------------------


def test_shape_of_strips_annotated_union_members() -> None:
    annotation = Annotated[list[UUID], Field(min_length=0)] | None
    assert shape_of(annotation) == (RefShape.COLLECTION, True, None)


def test_shape_of_disagreeing_union_is_scalar() -> None:
    assert shape_of(list[UUID] | dict[UUID, str]) == (RefShape.SCALAR, False, None)
    assert shape_of(list[UUID] | UUID | None) == (RefShape.SCALAR, True, None)


def test_variable_container_strips_annotated() -> None:
    assert _variable_container(Annotated[list[int], "meta"]) is list
    assert _variable_container(Annotated[dict[str, int], "meta"]) is dict


def test_optional_scalar_backref_gets_none_default() -> None:
    class Solo(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        owner_id: Annotated[UUID | None, backref("Thing", via="x"), scoped(Public)]

    # the implied default is structural; backref consistency stays lazy
    assert Solo.model_fields["owner_id"].default is None
    assert Solo(id=uuid4()).owner_id is None


# --- ref graph internals ----------------------------------------------------


def test_refgraph_repr_shows_edges() -> None:
    assert repr(Thing.__prism__.refs) == "RefGraph(Thing: no refs)"
    text = repr(DanglingTarget.__prism__.refs)
    assert "other_id->NoSuchModel" in text  # string targets shown unresolved


def test_unresolvable_string_target_raises() -> None:
    with pytest.raises(RefResolutionError, match="cannot resolve 'NoSuchModel'"):
        DanglingTarget.__prism__.refs["other_id"]


# --- projection builder internals -------------------------------------------


def test_scope_double_checked_cache_under_lock() -> None:
    """A thread that loses the build race gets the winner's class."""

    class Raced(ScopedModel):
        id: Annotated[UUID, scoped(Public)]

    passed_fast_path = threading.Event()
    original: dict[Any, Any] = Raced.__prism__.cache

    class SpyDict(dict[Any, Any]):
        def get(self, key: Any, default: Any = None) -> Any:
            passed_fast_path.set()
            return super().get(key, default)

    Raced.__prism__.cache = SpyDict(original)
    results: list[type[Any]] = []
    thread = threading.Thread(target=lambda: results.append(Raced.scope(Public)))
    with _build_lock:
        thread.start()
        # the thread misses the fast path, then blocks on the build lock we
        # hold; building the class now forces it down the in-lock cache hit
        assert passed_fast_path.wait(timeout=5)
        built = Raced.scope(Public)
    thread.join(timeout=5)
    assert results == [built]


def test_rewrite_preserves_nested_annotated_metadata() -> None:
    class Leg(ScopedModel):
        city: Annotated[str, scoped(Public)]
        code: Annotated[str, scoped(Internal)] = ""

    class Trip(ScopedModel):
        id: Annotated[UUID, scoped(Public)]
        legs: Annotated[
            list[Annotated[Leg, Field(description="leg")]], scoped(Public)
        ] = []

    projected = Trip.scope(Public)
    trip = projected(id=uuid4(), legs=[{"city": "Riga"}])
    leg = trip.legs[0]  # type: ignore[attr-defined]
    assert type(leg) is Leg.scope(Public)
    # the embedded edge was found through the nested Annotated as well
    assert Trip.__prism__.refs["legs"].target is Leg


def test_rewrite_leaves_bare_generics_alone() -> None:
    from pydantic_prism._internal.model import _BuildContext

    expr = as_expr(Public)
    assert _rewrite(list, expr, _BuildContext()) is list
    empty = tuple[()]  # subscripted, but with no argument types
    assert _rewrite(empty, expr, _BuildContext()) is empty


def test_validation_key_prefers_validation_alias() -> None:
    from pydantic.fields import FieldInfo

    from pydantic_prism._internal.model import _validation_key

    assert _validation_key("f", FieldInfo(validation_alias="v")) == "v"
    assert _validation_key("f", FieldInfo(alias="a")) == "a"
    assert _validation_key("f", FieldInfo()) == "f"


def test_wildcard_validator_carries_to_projection() -> None:
    from pydantic import field_validator

    class Loud(ScopedModel):
        name: Annotated[str, scoped(Public)]
        motto: Annotated[str, scoped(Internal)] = ""

        @field_validator("*")
        @classmethod
        def _strip(cls, value: object) -> object:
            return value.strip() if isinstance(value, str) else value

    projected = Loud.scope(Public)(name="  ada  ")
    assert projected.name == "ada"  # type: ignore[attr-defined]


def test_validator_on_dropped_fields_is_not_carried() -> None:
    from pydantic import field_validator

    class Guarded(ScopedModel):
        name: Annotated[str, scoped(Public)]
        token: Annotated[str, scoped(Internal)] = ""

        @field_validator("token")
        @classmethod
        def _forbid(cls, value: str) -> str:
            raise ValueError("tokens are never accepted in input")

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Guarded(name="x", token="t")
    projected = Guarded.scope(Public)(name="x")
    assert projected.name == "x"  # type: ignore[attr-defined]


# --- narrowing internals -----------------------------------------------------


class Inner(BaseModel):
    a: int = 0


def test_narrow_value_edge_shapes() -> None:
    # model annotation, non-mapping value: passed through
    assert _narrow_value(Inner, 42) == 42
    # nested Annotated is stripped
    assert _narrow_value(Annotated[Inner, "m"], {"a": 1, "b": 2}) == {"a": 1}
    # mapping annotation, non-mapping value: passed through
    assert _narrow_value(dict[str, Inner], 42) == 42
    # union with one model narrows mappings, leaves others
    assert _narrow_value(Inner | int, {"a": 1, "b": 2}) == {"a": 1}
    assert _narrow_value(Inner | int, 3) == 3
    # tuples: variadic and fixed
    assert _narrow_value(tuple[Inner, ...], [{"a": 1, "b": 2}]) == [{"a": 1}]
    assert _narrow_value(tuple[Inner, int], [{"a": 1, "b": 2}, 9]) == [{"a": 1}, 9]
    # tuple annotation with non-sequence value: passed through
    assert _narrow_value(tuple[Inner, ...], 42) == 42
