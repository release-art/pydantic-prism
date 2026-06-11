"""Before-validator ordering between @scoped_validator and an inherited hook.

pydantic v2 runs ``mode="before"`` validators child-first, so a
``@scoped_validator(mode="before")`` runs *before* a plain
``@model_validator(mode="before")`` inherited from a base. These tests pin the
trap, the ``run_inherited_before`` escape hatch, the class-definition warning,
and the ``parent_ordering="acknowledged"`` opt-out.
"""

from __future__ import annotations

import json
import warnings
from typing import Annotated, Any

import pytest
from pydantic import BaseModel, model_validator

from pydantic_prism import (
    PrismOrderingWarning,
    PrismWarning,
    Scope,
    ScopedModel,
    scoped,
    scoped_validator,
)


class Public(Scope): ...


class Internal(Public): ...


class Storage(Internal): ...


def _decode_hook(cls: type, data: Any) -> Any:
    """Idempotent JSON-decode of a stringified ``webpages`` column (a base hook)."""
    if isinstance(data, dict) and isinstance(data.get("webpages"), str):
        data = {**data, "webpages": json.loads(data["webpages"])}
    return data


class AzureTableModel(ScopedModel):
    """A canonical base that JSON-decodes columns in a before-validator."""

    @model_validator(mode="before")
    @classmethod
    def model_before_validation(cls, data: Any) -> Any:
        return _decode_hook(cls, data)


# --- 1. the trap: the scoped child runs first, sees undecoded data ------------


def test_scoped_before_runs_first_and_sees_undecoded_data() -> None:
    """Without the helper, the child iterates the still-encoded string."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PrismOrderingWarning)

        class Row(AzureTableModel, default_scope=Storage):
            webpages: Annotated[list[str], scoped(Public)] = []
            first_char: Annotated[str, scoped(Internal)] = ""

            @scoped_validator(Storage, mode="before")
            @classmethod
            def derive(cls, data: Any) -> Any:
                # No run_inherited_before: webpages is still '["..."]' here.
                if isinstance(data, dict) and data.get("webpages"):
                    data = {**data, "first_char": data["webpages"][0]}
                return data

    row = Row(webpages=json.dumps(["http://a.com", "http://b.com"]))
    # The child saw the raw JSON string and took its first *character*.
    assert row.first_char == "["
    # The base hook still ran afterwards, so the field itself is correct.
    assert row.webpages == ["http://a.com", "http://b.com"]


# --- 2. the fix: run_inherited_before makes the base hook run first -----------


class FixedRow(AzureTableModel, default_scope=Storage):
    webpages: Annotated[list[str], scoped(Public)] = []
    hostname: Annotated[str, scoped(Internal)] = ""

    @scoped_validator(Storage, mode="before", parent_ordering="acknowledged")
    @classmethod
    def derive_hostname(cls, data: Any) -> Any:
        data = cls.run_inherited_before(data)
        if isinstance(data, dict) and data.get("webpages") and not data.get("hostname"):
            data = {**data, "hostname": data["webpages"][0]}
        return data


def test_run_inherited_before_decodes_before_child_logic() -> None:
    row = FixedRow(webpages=json.dumps(["http://a.com", "http://b.com"]))
    assert row.hostname == "http://a.com"
    assert row.webpages == ["http://a.com", "http://b.com"]


def test_run_inherited_before_is_idempotent_under_double_run() -> None:
    """The base hook runs again under pydantic; a guarded hook is a no-op."""
    row = FixedRow(webpages=["http://already.com"])  # already native
    assert row.hostname == "http://already.com"
    assert row.webpages == ["http://already.com"]


class CarriedBase(BaseModel):
    """A non-ScopedModel base whose before-hook survives projection."""

    @model_validator(mode="before")
    @classmethod
    def decode(cls, data: Any) -> Any:
        return _decode_hook(cls, data)


class CarriedRow(
    CarriedBase,
    ScopedModel,
    default_scope=Storage,
    projection_bases=(CarriedBase,),
):
    webpages: Annotated[list[str], scoped(Public)] = []
    hostname: Annotated[str, scoped(Internal)] = ""

    @scoped_validator(Storage, mode="before", parent_ordering="acknowledged")
    @classmethod
    def derive_hostname(cls, data: Any) -> Any:
        data = cls.run_inherited_before(data)
        if isinstance(data, dict) and data.get("webpages") and not data.get("hostname"):
            data = {**data, "hostname": data["webpages"][0]}
        return data


def test_helper_works_on_projection_with_carried_base() -> None:
    """The scoped validator + carried base hook both survive projection."""
    proj = CarriedRow.scope(Storage, name="CarriedRowStorage")
    inst = proj.model_validate({"webpages": json.dumps(["http://p.com"])})
    assert inst.hostname == "http://p.com"
    assert inst.webpages == ["http://p.com"]


# --- 3. the warning fires at class definition ---------------------------------


def test_warning_fires_at_class_definition() -> None:
    with pytest.warns(PrismOrderingWarning) as record:

        class Row(AzureTableModel, default_scope=Storage):
            webpages: Annotated[list[str], scoped(Public)] = []
            hostname: Annotated[str, scoped(Internal)] = ""

            @scoped_validator(Storage, mode="before")
            @classmethod
            def derive(cls, data: Any) -> Any:
                return data

    assert len(record) == 1
    message = str(record[0].message)
    assert "Row.derive" in message
    assert "AzureTableModel.model_before_validation" in message
    assert "run_inherited_before" in message
    assert "parent_ordering='acknowledged'" in message
    assert Row(webpages=["http://x.com"]).webpages == ["http://x.com"]


def test_ordering_warning_is_a_prism_warning() -> None:
    assert issubclass(PrismOrderingWarning, PrismWarning)
    assert issubclass(PrismWarning, UserWarning)


# --- 4. parent_ordering="acknowledged" silences it ----------------------------


def test_acknowledged_silences_the_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", PrismOrderingWarning)

        class Row(AzureTableModel, default_scope=Storage):
            webpages: Annotated[list[str], scoped(Public)] = []

            @scoped_validator(Storage, mode="before", parent_ordering="acknowledged")
            @classmethod
            def derive(cls, data: Any) -> Any:
                return data

        assert Row(webpages=[]).webpages == []  # defined+usable, no escalated warning


def test_parent_ordering_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="acknowledged"):
        scoped_validator(Storage, mode="before", parent_ordering="nonsense")  # type: ignore[arg-type]


# --- 5. helper runs a 2-deep chain, parent-most last --------------------------


def test_run_inherited_before_runs_full_chain_in_order() -> None:
    calls: list[str] = []

    class Base1(ScopedModel):
        @model_validator(mode="before")
        @classmethod
        def base1_hook(cls, data: Any) -> Any:
            calls.append("base1")
            return data

    class Base2(Base1):
        @model_validator(mode="before")
        @classmethod
        def base2_hook(cls, data: Any) -> Any:
            calls.append("base2")
            return data

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PrismOrderingWarning)

        class Child(Base2, default_scope=Storage):
            x: Annotated[int, scoped(Public)] = 0

            @scoped_validator(Storage, mode="before")
            @classmethod
            def derive(cls, data: Any) -> Any:
                cls.run_inherited_before(data)
                return data

    calls.clear()
    Child(x=1)
    # The helper runs the inherited slice nearest-first (Base2) then parent-most
    # (Base1); pydantic then re-runs both — so the helper's slice leads.
    assert calls[:2] == ["base2", "base1"]


# --- no-trap cases: the warning must NOT fire ---------------------------------


def test_no_warning_without_inherited_before_hook() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", PrismOrderingWarning)

        class Plain(ScopedModel, default_scope=Storage):
            a: Annotated[str, scoped(Public)] = ""

            @scoped_validator(Storage, mode="before")
            @classmethod
            def derive(cls, data: Any) -> Any:
                return data

        assert Plain(a="x").a == "x"


def test_no_warning_for_after_mode_scoped_validator() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", PrismOrderingWarning)

        class Row(AzureTableModel, default_scope=Storage):
            webpages: Annotated[list[str], scoped(Public)] = []

            @scoped_validator(Storage, mode="after")
            def check(self) -> Row:
                return self

        assert isinstance(Row(webpages=[]), Row)


def test_no_warning_when_inherited_before_is_itself_scoped() -> None:
    """Two scoped before-validators stacking is the round-5 contract, not a trap."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", PrismOrderingWarning)

        class Base(ScopedModel):
            @scoped_validator(Public, mode="before")
            @classmethod
            def base_hook(cls, data: Any) -> Any:
                return data

        class Child(Base, default_scope=Storage):
            a: Annotated[str, scoped(Public)] = ""

            @scoped_validator(Storage, mode="before")
            @classmethod
            def derive(cls, data: Any) -> Any:
                return data

        assert Child(a="x").a == "x"


def test_warning_is_one_shot_per_validator() -> None:
    """Defining the same trap once warns once; the per-class set dedupes."""
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")

        class Row(AzureTableModel, default_scope=Storage):
            webpages: Annotated[list[str], scoped(Public)] = []

            @scoped_validator(Storage, mode="before")
            @classmethod
            def derive(cls, data: Any) -> Any:
                return data

        # A rebuild re-runs collection but must not re-warn for the same validator.
        Row.model_rebuild(force=True)

    ordering = [r for r in record if issubclass(r.category, PrismOrderingWarning)]
    assert len(ordering) == 1
    assert Row(webpages=["http://x.com"]).webpages == ["http://x.com"]


# --- the trap also fires for a non-ScopedModel carried base -------------------


def test_warning_for_plain_base_hook() -> None:
    """The base hook need not live on a ScopedModel — a carried base counts too."""

    class TableRowBase(BaseModel):
        @model_validator(mode="before")
        @classmethod
        def decode(cls, data: Any) -> Any:
            return _decode_hook(cls, data)

    with pytest.warns(PrismOrderingWarning, match="TableRowBase.decode"):

        class Row(
            TableRowBase,
            ScopedModel,
            default_scope=Storage,
            projection_bases=(TableRowBase,),
        ):
            webpages: Annotated[list[str], scoped(Public)] = []

            @scoped_validator(Storage, mode="before")
            @classmethod
            def derive(cls, data: Any) -> Any:
                return data

    row = Row(webpages=json.dumps(["http://b.com"]))
    assert row.webpages == ["http://b.com"]  # the carried base hook still decodes
