"""Tests for LLM tool-schema derivation (``tool_schema`` + ``toolschema``)."""

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Optional, Union, cast

import pytest

from pydantic_prism import (
    Scope,
    ScopedModel,
    ToolProvider,
    ToolSchemaDepthWarning,
    scoped,
)


@contextmanager
def no_depth_warning() -> Iterator[None]:
    """Assert no ``ToolSchemaDepthWarning`` is emitted in the block."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        yield
    assert not [w for w in caught if issubclass(w.category, ToolSchemaDepthWarning)]


class Public(Scope): ...


class Internal(Public): ...


class Address(ScopedModel):
    street: Annotated[str, scoped(Public)]
    note: Annotated[Optional[str], scoped(Public)] = None  # noqa: UP045


class User(ScopedModel):
    """A user."""

    id: Annotated[int, scoped(Public)]
    email: Annotated[str, scoped(Internal)]
    nickname: Annotated[Optional[str], scoped(Public)] = None  # noqa: UP045
    address: Annotated[Optional[Address], scoped(Public)] = None  # noqa: UP045


# --- envelopes -------------------------------------------------------------


def test_openai_strict_envelope() -> None:
    tool = User.tool_schema(Public, provider="openai")
    assert tool["type"] == "function"
    fn = tool["function"]
    assert fn["name"] == "UserPublic"
    assert fn["strict"] is True
    # Falls back to the canonical model's docstring, not the auto projection doc.
    assert fn["description"] == "A user."
    params = fn["parameters"]
    assert params["additionalProperties"] is False
    # Every property is required, and the hidden Internal field is absent.
    assert set(params["required"]) == {"id", "nickname", "address"}
    assert "email" not in params["properties"]


def test_anthropic_envelope_shape() -> None:
    tool = User.scope(Public).tool_schema(provider="anthropic", strict=False)
    assert set(tool) == {"name", "input_schema", "description"}
    assert tool["name"] == "UserPublic"
    assert tool["input_schema"]["type"] == "object"


def test_mistral_uses_openai_compatible_envelope() -> None:
    mistral = User.tool_schema(Public, provider="mistral")
    openai = User.tool_schema(Public, provider="openai")
    # Mistral shares the OpenAI tools format exactly.
    assert mistral == openai
    assert mistral["type"] == "function"
    assert mistral["function"]["strict"] is True


def test_mistral_non_strict_leaves_schema_faithful() -> None:
    fn = User.tool_schema(Public, provider="mistral", strict=False)["function"]
    assert fn["strict"] is False
    assert "additionalProperties" not in fn["parameters"]


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError, match="unknown tool provider"):
        User.scope(Public).tool_schema(provider=cast(ToolProvider, "bogus"))


# --- strict normalization --------------------------------------------------


def test_strict_marks_optionals_nullable_and_drops_default() -> None:
    params = User.tool_schema(Public, provider="openai")["function"]["parameters"]
    nickname = params["properties"]["nickname"]
    assert {"type": "null"} in nickname["anyOf"]
    assert "default" not in nickname


def test_strict_recurses_into_defs() -> None:
    params = User.tool_schema(Public, provider="openai")["function"]["parameters"]
    address_def = params["$defs"]["AddressPublic"]
    assert address_def["additionalProperties"] is False
    assert set(address_def["required"]) == {"street", "note"}


def test_strict_recurses_into_array_items() -> None:
    class Tagged(ScopedModel):
        tags: Annotated[list[Address], scoped(Public)]

    params = Tagged.tool_schema(Public, provider="openai")["function"]["parameters"]
    assert params["properties"]["tags"]["type"] == "array"
    # The element model in $defs is strictified too.
    assert params["$defs"]["AddressPublic"]["additionalProperties"] is False


def test_non_strict_leaves_required_untouched() -> None:
    params = User.scope(Public).tool_schema(provider="anthropic", strict=False)[
        "input_schema"
    ]
    # pydantic only requires fields without a default.
    assert params["required"] == ["id"]
    assert "additionalProperties" not in params


def test_bare_type_optional_is_wrapped() -> None:
    class Counter(ScopedModel):
        n: Annotated[int, scoped(Public)] = 0

    n = Counter.tool_schema(Public, provider="openai")["function"]["parameters"][
        "properties"
    ]["n"]
    assert n["anyOf"] == [{"type": "integer"}, {"type": "null"}]
    assert "default" not in n


def test_union_optional_appends_null() -> None:
    class Mix(ScopedModel):
        v: Annotated[Union[str, int], scoped(Public)] = "x"  # noqa: UP007

    v = Mix.tool_schema(Public, provider="openai")["function"]["parameters"][
        "properties"
    ]["v"]
    assert {"type": "null"} in v["anyOf"]
    # The original members survive alongside the injected null.
    assert {"type": "string"} in v["anyOf"]
    assert {"type": "integer"} in v["anyOf"]


# --- envelope=False (bare parameters schema) -------------------------------


def test_envelope_false_returns_bare_parameters() -> None:
    bare = User.tool_schema(Public, provider="openai", envelope=False)
    enveloped = User.tool_schema(Public, provider="openai")
    # The bare schema is exactly what the envelope nests under "parameters".
    assert bare == enveloped["function"]["parameters"]
    assert bare["type"] == "object"
    assert "function" not in bare


def test_envelope_false_still_normalizes_under_strict() -> None:
    bare = User.tool_schema(Public, provider="openai", envelope=False, strict=True)
    assert bare["additionalProperties"] is False
    assert set(bare["required"]) == {"id", "nickname", "address"}


def test_envelope_false_non_strict_is_faithful() -> None:
    bare = User.tool_schema(Public, provider="anthropic", envelope=False, strict=False)
    assert bare["required"] == ["id"]
    assert "additionalProperties" not in bare


def test_envelope_false_still_warns_on_depth() -> None:
    class N6(ScopedModel):
        v: Annotated[str, scoped(Public)]

    class N5(ScopedModel):
        c: Annotated[N6, scoped(Public)]

    class N4(ScopedModel):
        c: Annotated[N5, scoped(Public)]

    class N3(ScopedModel):
        c: Annotated[N4, scoped(Public)]

    class N2(ScopedModel):
        c: Annotated[N3, scoped(Public)]

    class N1(ScopedModel):
        c: Annotated[N2, scoped(Public)]

    with pytest.warns(ToolSchemaDepthWarning):
        N1.tool_schema(Public, provider="openai", envelope=False)


# --- name / description sourcing -------------------------------------------


def test_name_and_description_override() -> None:
    fn = User.tool_schema(
        Public, provider="openai", name="create_user", description="Make a user."
    )["function"]
    assert fn["name"] == "create_user"
    assert fn["description"] == "Make a user."


def test_description_omitted_when_absent() -> None:
    class Bare(ScopedModel):
        x: Annotated[int, scoped(Public)]

    fn = Bare.tool_schema(Public, provider="openai")["function"]
    assert "description" not in fn


def test_auto_projection_doc_never_leaks_as_description() -> None:
    fn = User.tool_schema(Public, provider="openai")["function"]
    assert "Projection of" not in fn["description"]


def test_per_scope_model_description_is_kept() -> None:
    # A description on the Scope class lands on the projection root; it is a
    # deliberate, meaningful tool description and must win over the canonical doc.
    class Tool(Scope, description="Look up the weather."): ...

    class Weather(ScopedModel):
        """internal docstring, should not be used"""

        city: Annotated[str, scoped(Tool)]

    fn = Weather.tool_schema(Tool, provider="openai")["function"]
    assert fn["description"] == "Look up the weather."


# --- API equivalence + composition -----------------------------------------


def test_convenience_matches_projection_method() -> None:
    assert User.tool_schema(Public, provider="openai") == User.scope(
        Public
    ).tool_schema(provider="openai")


def test_composes_with_input_output() -> None:
    # input() drops read-only fields; tool_schema works on any projection.
    schema = User.input(Public).tool_schema(provider="openai")["function"]["parameters"]
    assert schema["additionalProperties"] is False


def test_default_scope_fallback() -> None:
    class Doc(ScopedModel, default_scope=Public):
        body: Annotated[str, scoped(Public)]
        secret: Annotated[str, scoped(Internal)]

    fn = Doc.tool_schema(provider="openai")["function"]
    assert "secret" not in fn["parameters"]["properties"]


def test_missing_scope_without_default_raises() -> None:
    with pytest.raises(TypeError, match="requires a scope"):
        User.tool_schema()


# --- depth warning ---------------------------------------------------------


def test_shallow_model_does_not_warn() -> None:
    with no_depth_warning():
        User.tool_schema(Public, provider="openai")


def test_deep_nesting_warns() -> None:
    class N6(ScopedModel):
        v: Annotated[str, scoped(Public)]

    class N5(ScopedModel):
        c: Annotated[N6, scoped(Public)]

    class N4(ScopedModel):
        c: Annotated[N5, scoped(Public)]

    class N3(ScopedModel):
        c: Annotated[N4, scoped(Public)]

    class N2(ScopedModel):
        c: Annotated[N3, scoped(Public)]

    class N1(ScopedModel):
        c: Annotated[N2, scoped(Public)]

    with pytest.warns(ToolSchemaDepthWarning, match="levels deep"):
        N1.tool_schema(Public, provider="openai")


def test_recursive_model_warns() -> None:
    class Node(ScopedModel):
        name: Annotated[str, scoped(Public)]
        child: Annotated[Optional["Node"], scoped(Public)] = None  # noqa: UP045

    Node.model_rebuild()
    with pytest.warns(ToolSchemaDepthWarning, match="recursive"):
        Node.tool_schema(Public, provider="openai")


def test_depth_not_checked_without_strict_or_for_other_providers() -> None:
    class N6(ScopedModel):
        v: Annotated[str, scoped(Public)]

    class N5(ScopedModel):
        c: Annotated[N6, scoped(Public)]

    class N4(ScopedModel):
        c: Annotated[N5, scoped(Public)]

    class N3(ScopedModel):
        c: Annotated[N4, scoped(Public)]

    class N2(ScopedModel):
        c: Annotated[N3, scoped(Public)]

    class N1(ScopedModel):
        c: Annotated[N2, scoped(Public)]

    with no_depth_warning():
        N1.tool_schema(Public, provider="openai", strict=False)
        N1.tool_schema(Public, provider="anthropic")
        # The 5-level limit is OpenAI-specific; Mistral is not subject to it.
        N1.tool_schema(Public, provider="mistral")


# --- valid-against-OpenAI-constraints self-check ---------------------------


def _assert_openai_strict_valid(schema: dict, defs: dict) -> None:
    """Every object lists all properties as required + forbids extras."""
    if schema.get("type") == "object" or "properties" in schema:
        props = schema.get("properties", {})
        assert schema.get("additionalProperties") is False
        assert set(schema.get("required", [])) == set(props)
        for sub in props.values():
            assert "default" not in sub
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for sub in schema.get(key, []):
            _assert_openai_strict_valid(sub, defs)
    for key in ("items", "properties"):
        value = schema.get(key)
        if isinstance(value, dict):
            children = value.values() if key == "properties" else [value]
            for child in children:
                _assert_openai_strict_valid(child, defs)


def test_emitted_strict_schema_satisfies_openai_constraints() -> None:
    params = User.tool_schema(Public, provider="openai")["function"]["parameters"]
    defs = params.get("$defs", {})
    _assert_openai_strict_valid(params, defs)
    for definition in defs.values():
        _assert_openai_strict_valid(definition, defs)
