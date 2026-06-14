"""Round 16: the classification axis, redacted views, and data-flow reports."""

from __future__ import annotations

from pathlib import Path

import pytest

from pydantic_prism import Classification, FlowReport, Scope
from pydantic_prism._internal.codegen.cli import (
    main,  # pyright: ignore[reportPrivateUsage]
)

from . import _flow_fixtures as fx

_FX = "tests._flow_fixtures"


# --- the Classification base ----------------------------------------------


def test_classification_is_a_scope_but_distinct() -> None:
    assert issubclass(fx.Pii, Classification)
    assert issubclass(fx.Pii, Scope)  # a classification *is* a scope
    # A classification is a real scope: it can be projected to directly.
    pii_view = fx.User.scope(fx.Pii)
    assert set(pii_view.model_fields) == {"email", "secret_note"}


def test_classification_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError, match="used as a class, never instantiated"):
        fx.Pii()


# --- classifications() / classified_fields() -------------------------------


def test_classifications_are_the_classification_slice() -> None:
    assert fx.User.classifications() == frozenset({fx.Pii, fx.Secret})
    # A model with only visibility scopes carries no classifications.
    assert fx.Org.classifications() == frozenset()


def test_classified_fields_reads_tags_off_each_field() -> None:
    assert fx.User.classified_fields() == {
        "email": frozenset({fx.Pii}),
        "secret_note": frozenset({fx.Pii, fx.Secret}),
    }
    # No classified fields → empty mapping (id/org_id are visibility-only).
    assert fx.Org.classified_fields() == {}


def test_dimensions_groups_scopes_by_axis_structurally() -> None:
    # The visibility ladder and the Classification axis are inferred from the
    # inheritance forest — no marker check involved.
    assert fx.User.dimensions() == {
        fx.Public: frozenset({fx.Public, fx.Internal}),
        Classification: frozenset({fx.Pii, fx.Secret}),
    }
    # Single-axis model → one dimension.
    assert fx.Org.dimensions() == {fx.Public: frozenset({fx.Public})}


# --- redacted() ------------------------------------------------------------


def test_redacted_strips_every_classification_by_default() -> None:
    audit = fx.User.redacted(fx.Internal)
    # Internal view minus all PII/Secret: classified fields gone, refs survive.
    assert set(audit.model_fields) == {"id", "org_id"}
    assert audit.__prism__.refs["org_id"].target is fx.Org


def test_redacted_explicit_strip_keeps_other_classifications() -> None:
    # Strip only Secret: the Pii-but-not-Secret field survives.
    audit = fx.User.redacted(fx.Internal, strip=fx.Secret)
    assert "email" in audit.model_fields  # Pii, not Secret
    assert "secret_note" not in audit.model_fields  # Pii AND Secret


def test_redacted_on_model_without_classifications_is_plain_projection() -> None:
    # No classifications declared → nothing to strip → identical to scope().
    assert fx.Org.redacted(fx.Public) is fx.Org.scope(fx.Public)


def test_redacted_forwards_name() -> None:
    audit = fx.User.redacted(fx.Internal, name="UserAudit")
    assert audit.__name__ == "UserAudit"


def test_redacted_requires_a_visibility_scope() -> None:
    with pytest.raises(TypeError, match="required positional argument"):
        fx.User.redacted()  # type: ignore[call-arg]  # visible is required


# --- data_flow() / FlowReport (structural) ---------------------------------


def test_data_flow_reports_every_reachable_tagged_field() -> None:
    report = fx.Account.data_flow()
    assert isinstance(report, FlowReport)
    assert bool(report) is True
    # Every reachable model with tagged fields is a node (BFS order).
    assert [n.model for n in report.nodes] == [fx.Account, fx.User, fx.Org]
    user = next(n for n in report.nodes if n.model is fx.User)
    # Each field's scopes are grouped by axis, inferred structurally — Pii lands
    # under its Classification root, visibility under Public, no marker import.
    by_field = {f.field_name: f.by_dimension for f in user.fields}
    assert by_field["email"] == {"Classification": ("Pii",), "Public": ("Public",)}
    # .labels is the flat, sorted view of all the field's scopes.
    email = next(f for f in user.fields if f.field_name == "email")
    assert email.labels == ("Pii", "Public")
    assert by_field["secret_note"] == {
        "Classification": ("Pii", "Secret"),
        "Public": ("Internal",),
    }


def test_flow_report_is_falsy_when_no_tagged_data_reachable() -> None:
    # Bare has no tagged fields and no refs.
    report = fx.Bare.data_flow()
    assert bool(report) is False
    assert report.nodes == ()
    assert report.edges == ()


def test_flow_report_as_dict_is_the_compliance_artifact() -> None:
    data = fx.Account.data_flow().as_dict()
    assert data["root"] == "Account"
    assert [n["model"] for n in data["nodes"]] == ["Account", "User", "Org"]
    user_node = next(n for n in data["nodes"] if n["model"] == "User")
    assert {
        "field": "secret_note",
        "dimensions": {"Classification": ["Pii", "Secret"], "Public": ["Internal"]},
    } in user_node["fields"]
    # The diamond re-reaches Org; every forward edge of the walk is recorded.
    edges = {(e["source"], e["field"], e["target"]) for e in data["edges"]}
    assert edges == {
        ("Account", "user_id", "User"),
        ("Account", "org_id", "Org"),
        ("User", "org_id", "Org"),
    }
    assert all(e["kind"] == "ref" for e in data["edges"])


def test_flow_report_to_mermaid_badges_fields_and_shows_hops() -> None:
    mermaid = fx.Account.data_flow().to_mermaid()
    assert mermaid.startswith("classDiagram")
    # Multi-axis User badges each field with its cross-dimension tags...
    assert "str secret_note [Internal, Pii, Secret]" in mermaid
    # ...single-axis Account/Org appear with un-badged fields.
    assert "class Account" in mermaid
    assert "class Org" in mermaid
    # Edges are labelled with the referencing field.
    assert "Account --> User : user_id" in mermaid


def test_flow_report_to_mermaid_direction() -> None:
    assert "direction LR" in fx.Account.data_flow().to_mermaid(direction="LR")


# --- prism flow CLI --------------------------------------------------------


def test_cli_flow_json_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["flow", f"{_FX}:Account"]) == 0
    out = capsys.readouterr().out
    assert '"root": "Account"' in out
    assert '"secret_note"' in out


def test_cli_flow_mermaid_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["flow", f"{_FX}:Account", "--format", "mermaid"]) == 0
    assert "classDiagram" in capsys.readouterr().out


def test_cli_flow_to_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "flow.json"
    assert main(["flow", f"{_FX}:Account", "--output", str(out)]) == 0
    assert '"root": "Account"' in out.read_text()
    assert "wrote json flow report" in capsys.readouterr().out


def test_cli_flow_rejects_non_model(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["flow", f"{_FX}:Pii"]) == 2  # a Scope, not a model
    assert "not a ScopedModel" in capsys.readouterr().err
