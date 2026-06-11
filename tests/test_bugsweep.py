"""Regression tests for the adversarial bug sweep (bugs 2-11)."""

import sys
import types
from collections.abc import Callable
from typing import Annotated, Any, get_args
from uuid import UUID

import pytest
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

from pydantic_prism import (
    EmptyProjectionError,
    ProjectionNameError,
    RefResolutionError,
    Scope,
    ScopedModel,
    backref,
    ref,
    scoped,
)


class Public(Scope): ...


class Internal(Public): ...


def _make_module(name: str, source: str, **injected: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(injected)
    sys.modules[name] = module
    exec(source, module.__dict__)
    return module


# --- bug 2: failed builds must commit nothing ------------------------------


class PoisonA(ScopedModel):
    name: Annotated[str, scoped(Public)]
    again: Annotated["PoisonA | None", scoped(Public)] = None


class PoisonB(ScopedModel):
    secret: Annotated[str, scoped(Internal)]  # nothing Public


class PoisonParent(ScopedModel):
    a: Annotated[PoisonA, scoped(Public)]
    b: Annotated[PoisonB, scoped(Public)]


def test_failed_build_leaves_no_poisoned_cache() -> None:
    with pytest.raises(EmptyProjectionError):
        PoisonParent.scope(Public)  # PoisonAPublic was staged before B failed
    # The sibling staged during the failed build must not be served broken.
    projected = PoisonA.scope(Public)
    value = projected.model_validate({"name": "x", "again": {"name": "y"}})
    assert type(value.again) is projected
    # And the failing build keeps failing cleanly, not with a half-built class.
    with pytest.raises(EmptyProjectionError):
        PoisonParent.scope(Public)


# --- bug 3: from_canonical / from_projection under forbid + aliases --------


class StrictAddr(ScopedModel):
    model_config = ConfigDict(extra="forbid")
    city: Annotated[str, scoped(Public)]
    plus_code: Annotated[str, scoped(Internal)] = ""


class StrictShip(ScopedModel):
    model_config = ConfigDict(extra="forbid")
    sid: Annotated[int, scoped(Public)]
    dest: Annotated[StrictAddr, scoped(Public)]
    stops: Annotated[list[StrictAddr], scoped(Public)] = []  # noqa: RUF012


def test_from_canonical_filters_nested_under_extra_forbid() -> None:
    ship = StrictShip(
        sid=1,
        dest=StrictAddr(city="Riga", plus_code="9G86"),
        stops=[StrictAddr(city="Oslo", plus_code="XX")],
    )
    pub = StrictShip.scope(Public).from_canonical(ship)
    assert pub.dest.model_dump() == {"city": "Riga"}
    assert pub.stops[0].model_dump() == {"city": "Oslo"}


class CamelUser(ScopedModel):
    model_config = ConfigDict(alias_generator=to_camel)
    display_name: Annotated[str, scoped(Public)]
    secret_note: Annotated[str, scoped(Internal)] = ""


def test_from_canonical_with_alias_generator() -> None:
    user = CamelUser(displayName="Ada", secretNote="s")
    pub = CamelUser.scope(Public).from_canonical(user)
    assert pub.display_name == "Ada"


def test_from_projection_with_alias_generator_and_python_name_extras() -> None:
    pub = CamelUser.scope(Public)(displayName="Ada")
    back = CamelUser.from_projection(pub, secret_note="s")
    assert back.secret_note == "s"


# --- bug 4: same-named canonical models in one build ------------------------

_ITEM_A_SRC = """
from typing import Annotated
from pydantic_prism import ScopedModel, scoped

class Item(ScopedModel):
    name: Annotated[str, scoped(PUBLIC)]
    again: Annotated["Item | None", scoped(PUBLIC)] = None
"""

_ITEM_B_SRC = """
from typing import Annotated
from pydantic_prism import ScopedModel, scoped

class Item(ScopedModel):
    count: Annotated[int, scoped(PUBLIC)]
    again: Annotated["Item | None", scoped(PUBLIC)] = None
"""


def test_same_named_models_resolve_to_distinct_projections() -> None:
    mod_a = _make_module("prism_test_mod_a", _ITEM_A_SRC, PUBLIC=Public)
    mod_b = _make_module("prism_test_mod_b", _ITEM_B_SRC, PUBLIC=Public)
    item_a, item_b = mod_a.Item, mod_b.Item

    class Holder(ScopedModel):
        a: Annotated[item_a, scoped(Public)]
        b: Annotated[item_b, scoped(Public)]

    Holder.scope(Public)  # one build containing two cyclic "ItemPublic" classes
    a_pub, b_pub = item_a.scope(Public), item_b.scope(Public)
    assert a_pub is not b_pub
    a = a_pub.model_validate({"name": "x", "again": {"name": "y"}})
    assert type(a.again) is a_pub
    b = b_pub.model_validate({"count": 1, "again": {"count": 2}})
    assert type(b.again) is b_pub
    # the JSON schema embeds both shapes, not one of them twice
    schema = str(Holder.scope(Public).model_json_schema())
    assert "'name'" in schema and "'count'" in schema


# --- bug 6 / bug 10: name collisions are explicit errors ---------------------


def test_same_named_scopes_canonicalize_consistently() -> None:
    scope_src = "from pydantic_prism import Scope\nclass Night(Scope): ...\n"
    s1 = _make_module("prism_test_scopes_1", scope_src).Night
    s2 = _make_module("prism_test_scopes_2", scope_src).Night
    # Two same-named scopes from different modules stay distinct yet canonicalize
    # consistently in the *expression* algebra (module-qualified ordering). They
    # may not, however, share one model — see the next test.
    assert (s1 | s2) == (s2 | s1)
    assert hash(s1 | s2) == hash(s2 | s1)


def test_same_token_scopes_on_one_model_are_rejected() -> None:
    # Two scopes contributing the same projection-name token cannot share a
    # model: their projections would collide on one class name. Rejected eagerly,
    # at model definition — not lazily at the second .scope() build.
    scope_src = "from pydantic_prism import Scope\nclass Dusk(Scope): ...\n"
    d1 = _make_module("prism_test_scopes_3", scope_src).Dusk
    d2 = _make_module("prism_test_scopes_4", scope_src).Dusk
    with pytest.raises(ProjectionNameError, match="would share a class name"):

        class Collide(ScopedModel):
            x: Annotated[int, scoped(d1)]
            y: Annotated[int, scoped(d2)]

    # A distinct cls_name_token= on one scope resolves the clash.
    class DuskAlt(Scope, cls_name_token="Twilight"): ...

    class Ok(ScopedModel):
        x: Annotated[int, scoped(d1)]
        y: Annotated[int, scoped(DuskAlt)]

    names = {Ok.scope(d1).__name__, Ok.scope(DuskAlt).__name__}
    assert names == {"OkDusk", "OkTwilight"}


def test_explicit_name_reuse_with_different_expr_raises() -> None:
    class M(ScopedModel):
        x: Annotated[int, scoped(Public)]
        y: Annotated[int, scoped(Internal)]

    first = M.scope(Public, name="Same")
    with pytest.raises(ProjectionNameError):
        M.scope(Internal, name="Same")
    assert M.scope(Public, name="Same") is first


# --- bug 7: nested Annotated markers are rejected, not ignored --------------


def test_nested_scoped_marker_rejected() -> None:
    with pytest.raises(TypeError, match="top-level Annotated"):

        class Bad(ScopedModel):
            xs: Annotated[list[Annotated[UUID, scoped(Public)]], scoped(Public)]


def test_nested_ref_marker_rejected() -> None:
    with pytest.raises(TypeError, match="top-level Annotated"):

        class Bad(ScopedModel):
            ys: list[Annotated[UUID, ref("Whatever")]]


# --- bug 8: string refs on function-local models ----------------------------


class Decoy(ScopedModel):
    id: Annotated[UUID, scoped(Public)]


def test_closure_model_string_ref_refuses_instead_of_guessing() -> None:
    class Local(ScopedModel):
        other: Annotated[UUID, ref("Decoy"), scoped(Public)]

    with pytest.raises(RefResolutionError, match="inside a function"):
        Local.__refs__["other"]


# --- bug 9: backref default implication respects the container type ---------


class Pairs(ScopedModel):
    pair: Annotated[tuple[UUID, UUID], backref("Decoy", via="id"), scoped(Public)]


class Stream(ScopedModel):
    items: Annotated[tuple[UUID, ...], backref("Decoy", via="id"), scoped(Public)]


def test_fixed_tuple_backref_stays_required() -> None:
    assert Pairs.model_fields["pair"].is_required()


def test_variable_tuple_backref_gets_empty_default() -> None:
    assert Stream.model_fields["items"].default_factory is tuple


def test_union_of_containers_is_many() -> None:
    class M(ScopedModel):
        ids: Annotated[list[UUID] | set[UUID], ref(Decoy), scoped(Public)] = []  # noqa: RUF012

    assert M.__refs__["ids"].many


# --- bug 11: Callable parameter lists are rewritten --------------------------


class Inner(ScopedModel):
    x: Annotated[int, scoped(Public)]


class WithCallable(ScopedModel):
    fn: Annotated[Callable[[Inner], Inner] | None, scoped(Public)] = None


def test_callable_parameters_projected() -> None:
    annotation = WithCallable.scope(Public).model_fields["fn"].annotation
    callable_ann = get_args(annotation)[0]  # strip | None
    params, ret = get_args(callable_ann)
    inner_public = Inner.scope(Public)
    assert params == [inner_public]
    assert ret is inner_public
