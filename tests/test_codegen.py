"""prism gen / prism check — stub generation, drift detection, CLI."""

from __future__ import annotations

import enum
import importlib
import importlib.util
import runpy
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

import pytest

from pydantic_prism import StaleProjectionStubError
from pydantic_prism._codegen import (
    CodegenError,
    Config,
    ProjectionSpec,
    _field_suffix,
    _import_lines,
    _Imports,
    _projections_in,
    _reject_name_clashes,
    _render_annotation,
    _render_bare,
    _render_literal,
    _render_scope_expr,
    generate,
    load_config,
    main,
)
from pydantic_prism._drift import assert_fresh, projection_signature
from pydantic_prism._scopes import ScopeExpr, as_expr

from . import _codegen_fixtures as fx


class _Color(enum.Enum):
    RED = 1


# --- helpers ---------------------------------------------------------------


def _config(tmp_path: Path, **kw: Any) -> Config:
    return Config(
        output=tmp_path / "genmod.py",
        modules=kw.get("modules", ("tests._codegen_fixtures",)),
        projections=kw.get("projections", ()),
        root=tmp_path,
    )


@pytest.fixture
def import_generated(tmp_path: Path) -> Iterator[Callable[[Config], Any]]:
    """Generate to a temp module, import it, and clean up sys.path/modules."""
    added: list[str] = []

    def run(config: Config) -> Any:
        text = generate(config)
        config.output.write_text(text, encoding="utf-8")
        sys.path.insert(0, str(tmp_path))
        mod = importlib.import_module(config.output.stem)
        added.append(config.output.stem)
        return mod

    yield run

    for name in added:
        sys.modules.pop(name, None)
    if str(tmp_path) in sys.path:
        sys.path.remove(str(tmp_path))


# --- config loading --------------------------------------------------------


def _write_pyproject(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_load_config_full(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
        [tool.pydantic-prism]
        output = "pkg/_generated.py"
        modules = ["tests._codegen_fixtures"]

        [[tool.pydantic-prism.projections]]
        model = "tests._codegen_fixtures:Screenshot"
        scopes = ["tests._codegen_fixtures:Public", "tests._codegen_fixtures:Update"]
        name = "ScreenshotPub"
        """,
    )
    config = load_config(pyproject)
    assert config.output == tmp_path.resolve() / "pkg/_generated.py"
    assert config.modules == ("tests._codegen_fixtures",)
    assert config.projections == (
        ProjectionSpec(
            model="tests._codegen_fixtures:Screenshot",
            scopes=(
                "tests._codegen_fixtures:Public",
                "tests._codegen_fixtures:Update",
            ),
            name="ScreenshotPub",
        ),
    )


@pytest.mark.parametrize(
    "body",
    [
        "[tool.other]\nx = 1\n",  # no table
        '[tool.pydantic-prism]\nmodules = ["m"]\n',  # no output
        '[tool.pydantic-prism]\noutput = "o.py"\n',  # selects nothing
    ],
)
def test_load_config_errors(tmp_path: Path, body: str) -> None:
    with pytest.raises(CodegenError):
        load_config(_write_pyproject(tmp_path, body))


@pytest.mark.parametrize(
    "entry",
    [
        '"not-a-table"',
        '{ scopes = ["m:S"] }',  # no model
        '{ model = "m:M" }',  # no scopes
        '{ model = "m:M", scopes = [] }',  # empty scopes
        '{ model = "m:M", scopes = [1] }',  # non-string scope
        '{ model = "m:M", scopes = ["m:S"], name = 3 }',  # bad name
    ],
)
def test_load_config_bad_projection_entry(tmp_path: Path, entry: str) -> None:
    body = f'[tool.pydantic-prism]\noutput = "o.py"\nprojections = [{entry}]\n'
    with pytest.raises(CodegenError):
        load_config(_write_pyproject(tmp_path, body))


# --- discovery / resolution errors -----------------------------------------


def test_resolve_errors(tmp_path: Path) -> None:
    model = "tests._codegen_fixtures:Screenshot"
    for spec in (
        ProjectionSpec("no-colon", ("tests._codegen_fixtures:Public",)),  # bad path
        ProjectionSpec(model, ("bad.module:X",)),  # import error
        ProjectionSpec(model, ("tests._codegen_fixtures:Nope",)),  # attribute error
    ):
        with pytest.raises(CodegenError):
            generate(_config(tmp_path, modules=(), projections=(spec,)))


def test_projection_target_not_a_model(tmp_path: Path) -> None:
    # 'Public' is a Scope, not a ScopedModel.
    spec = ProjectionSpec(
        "tests._codegen_fixtures:Public", ("tests._codegen_fixtures:Public",)
    )
    with pytest.raises(CodegenError, match="not a ScopedModel"):
        generate(_config(tmp_path, modules=(), projections=(spec,)))


def test_no_projections_to_generate(tmp_path: Path) -> None:
    # A module with no scoped models yields nothing.
    with pytest.raises(CodegenError, match="no projections"):
        generate(_config(tmp_path, modules=("pydantic_prism.errors",)))


# --- end-to-end generation -------------------------------------------------


def test_generate_contains_expected_shapes(tmp_path: Path) -> None:
    spec = ProjectionSpec(
        "tests._codegen_fixtures:Screenshot",
        ("tests._codegen_fixtures:Update",),
        name="ScreenshotPatch",  # exercises the name= override path
    )
    text = generate(_config(tmp_path, projections=(spec,)))
    # nested projection referenced statically
    assert "tags: list[TagPublic]" in text
    # partial fields optional with None default
    assert "container_name: str | None = None" in text
    # carried base in the shim bases
    assert "class ScreenshotRef(CarrierBase, Projection):" in text
    # field-default variants
    assert "count: int = 0" in text
    assert "items: list[str] = Field(default_factory=list)" in text
    # name override flows into the else alias (repr -> single quotes)
    assert "name='ScreenshotPatch'" in text
    # banner + structure
    assert text.startswith("# This file is generated by `prism gen`")
    assert "if TYPE_CHECKING:" in text and "else:" in text


def test_field_descriptions_become_attribute_docstrings(tmp_path: Path) -> None:
    spec = ProjectionSpec(
        "tests._codegen_fixtures:Screenshot", ("tests._codegen_fixtures:Storage",)
    )
    text = generate(_config(tmp_path, modules=(), projections=(spec,)))
    # Screenshot.container_name carries a description (see fixtures) -> docstring
    assert "'A storage container name.'" in text


def test_description_change_shifts_drift_signature() -> None:
    from pydantic import Field

    from pydantic_prism._drift import projection_signature

    class M(fx.ScopedModel):
        x: Annotated[str, fx.scoped(fx.Public), Field(description="one")]

    sig_one = projection_signature(M.scope(fx.Public))

    class N(fx.ScopedModel):
        x: Annotated[str, fx.scoped(fx.Public), Field(description="two")]

    assert projection_signature(N.scope(fx.Public)) != sig_one  # desc is in the sig


def test_generated_module_imports_with_identity(
    import_generated: Callable[[Config], Any], tmp_path: Path
) -> None:
    spec = ProjectionSpec(
        "tests._codegen_fixtures:Screenshot", ("tests._codegen_fixtures:Update",)
    )
    mod = import_generated(_config(tmp_path, projections=(spec,)))
    # identity: the alias IS the cached projection
    assert mod.ScreenshotRef is fx.Screenshot.scope(fx.Ref)
    # carried base survives (isinstance + method)
    assert issubclass(mod.ScreenshotStorage, fx.CarrierBase)
    instance = mod.ScreenshotStorage(
        timestamp="2020-01-01T00:00:00",  # type: ignore[arg-type]
        website_id="00000000-0000-0000-0000-000000000001",
        container_name="c",
    )
    assert instance.carrier() == "ScreenshotStorage"
    # partial projection: all optional
    assert mod.ScreenshotUpdate().model_dump(exclude_none=True) == {}


# --- CLI -------------------------------------------------------------------


def _cli_pyproject(tmp_path: Path, *, name: bool = False) -> Path:
    projection = (
        "\n[[tool.pydantic-prism.projections]]\n"
        'model = "tests._codegen_fixtures:Screenshot"\n'
        'scopes = ["tests._codegen_fixtures:Update"]\n'
        if name
        else ""
    )
    return _write_pyproject(
        tmp_path,
        "[tool.pydantic-prism]\n"
        'output = "out.py"\n'
        'modules = ["tests._codegen_fixtures"]\n' + projection,
    )


def test_main_gen_then_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pyproject = _cli_pyproject(tmp_path, name=True)
    assert main(["gen", "--config", str(pyproject)]) == 0
    assert (tmp_path / "out.py").exists()
    assert "wrote" in capsys.readouterr().out
    # freshly generated -> check passes
    assert main(["check", "--config", str(pyproject)]) == 0
    assert "up to date" in capsys.readouterr().out


def test_main_check_stale(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pyproject = _cli_pyproject(tmp_path)
    main(["gen", "--config", str(pyproject)])
    capsys.readouterr()
    (tmp_path / "out.py").write_text("# tampered\n", encoding="utf-8")
    assert main(["check", "--config", str(pyproject)]) == 1
    assert "out of date" in capsys.readouterr().err


def test_main_check_missing_file(tmp_path: Path) -> None:
    # check with no generated file present is treated as stale.
    pyproject = _cli_pyproject(tmp_path)
    assert main(["check", "--config", str(pyproject)]) == 1


def test_main_config_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pyproject = _write_pyproject(tmp_path, "[tool.other]\n")
    assert main(["gen", "--config", str(pyproject)]) == 2
    assert "prism:" in capsys.readouterr().err


def test_main_missing_config_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.toml"
    assert main(["gen", "--config", str(missing)]) == 2
    assert "prism:" in capsys.readouterr().err


def test_module_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["prism"])  # no subcommand -> argparse exits 2
    with pytest.raises(SystemExit):
        runpy.run_module("pydantic_prism", run_name="__main__")


# --- drift signature -------------------------------------------------------


def test_signature_stable_and_assert_fresh() -> None:
    proj = fx.Screenshot.scope(fx.Ref)
    sig = projection_signature(proj)
    assert sig == projection_signature(proj)  # deterministic
    assert_fresh(proj, sig)  # no raise
    with pytest.raises(StaleProjectionStubError, match="stale"):
        assert_fresh(proj, "0000000000000000")


# --- rendering helpers -----------------------------------------------------


def test_render_annotation_variants() -> None:
    imp = _Imports()
    assert _render_annotation(int, imp) == "int"
    assert _render_annotation(Optional[int], imp) == "int | None"  # noqa: UP045
    assert _render_annotation(list[str], imp) == "list[str]"
    assert _render_annotation(dict[str, UUID], imp) == "dict[str, UUID]"
    assert _render_annotation(tuple[int, ...], imp) == "tuple[int, ...]"
    assert (
        _render_annotation(Literal["a", 1, True, None], imp)
        == "Literal['a', 1, True, None]"
    )
    # Annotated metadata is stripped (typing only)
    assert _render_annotation(Annotated[int, "meta"], imp) == "int"
    assert ("uuid", "UUID") in imp.typing_only
    assert ("typing", "Literal") in imp.typing_only


def test_render_bare_any_and_error() -> None:
    imp = _Imports()
    assert _render_bare(Any, imp) == "Any"
    assert ("typing", "Any") in imp.typing_only
    with pytest.raises(CodegenError, match="cannot render annotation"):
        _render_bare(42, imp)


def test_render_literal_enum_and_error() -> None:
    imp = _Imports()
    assert _render_literal(_Color.RED, imp) == "_Color.RED"
    assert ("tests.test_codegen", "_Color") in imp.typing_only
    with pytest.raises(CodegenError, match="Literal value"):
        _render_literal(object(), imp)


def test_render_scope_expr_all_forms() -> None:
    imp = _Imports()
    a, b = as_expr(fx.Public), as_expr(fx.Ref)
    assert _render_scope_expr(a, imp) == "Public"
    assert _render_scope_expr(a | b, imp) == "(Public | Ref)"
    assert _render_scope_expr(a & b, imp) == "(Public & Ref)"
    assert _render_scope_expr(a - b, imp) == "(Public - Ref)"
    assert _render_scope_expr(~a, imp) == "~Public"
    assert ("tests._codegen_fixtures", "Public") in imp.runtime


def test_render_scope_expr_unknown() -> None:
    class Weird(ScopeExpr):
        pass

    with pytest.raises(CodegenError, match="scope expression"):
        _render_scope_expr(Weird(), _Imports())


def test_projections_in_through_callable_and_annotated() -> None:
    tag_public = fx.Tag.scope(fx.Public)
    # Callable parameter lists are walked...
    found = _projections_in(Callable[[tag_public], int])  # type: ignore[valid-type]
    assert tag_public in found
    # ...and Annotated metadata is stripped during the walk.
    assert _projections_in(Annotated[tag_public, "meta"]) == [tag_public]


def test_reject_name_clashes() -> None:
    a = fx.Screenshot.scope(fx.Public, name="Dup")
    b = fx.Tag.scope(fx.Public, name="Dup")
    _reject_name_clashes([a])  # no clash
    with pytest.raises(CodegenError, match="share the generated name"):
        _reject_name_clashes([a, b])


def test_import_lines_grouping() -> None:
    pairs = {("b.mod", "Y"), ("a.mod", "B"), ("a.mod", "A")}
    assert _import_lines(pairs, "    ") == [
        "    from a.mod import A, B",
        "    from b.mod import Y",
    ]


def test_field_suffix_branches() -> None:
    imp = _Imports()
    fields = fx.Screenshot.scope(fx.Public).model_fields
    # required (website_id has no default)
    assert _field_suffix(fields["website_id"], imp) == ""
    # scalar default
    assert _field_suffix(fields["count"], imp) == " = 0"
    # builtin default_factory
    assert _field_suffix(fields["items"], imp) == " = Field(default_factory=list)"
    # other default value (mutable []) -> conservative, no suffix
    assert _field_suffix(fields["tags"], imp) == ""
    # non-builtin factory (uuid4) -> conservative, no suffix
    assert _field_suffix(fx.Tag.scope(fx.Ref).model_fields["id"], imp) == ""
    # forced-None default on a partial projection
    update = fx.Screenshot.scope(fx.Update).model_fields
    assert _field_suffix(update["container_name"], imp) == " = None"


# --- the static-typing payoff, checked by pyright --------------------------


def _has_pyright() -> bool:
    return (
        importlib.util.find_spec("pyright") is not None
        or shutil.which("pyright") is not None
    )


@pytest.mark.skipif(not _has_pyright(), reason="pyright not installed")
def test_generated_stub_gives_pyright_field_visibility(tmp_path: Path) -> None:
    """A consumer of a generated stub sees real fields; bad access is an error."""
    pkg = tmp_path / "site"
    pkg.mkdir()
    (pkg / "models.py").write_text(
        textwrap.dedent(
            """
            from __future__ import annotations
            from datetime import datetime
            from typing import Annotated
            from uuid import UUID, uuid4
            from pydantic import Field
            from pydantic_prism import Scope, ScopedModel, scoped

            class Ref(Scope): ...

            class Shot(ScopedModel, default_scope=Ref):
                id: Annotated[UUID, scoped(Ref)] = Field(default_factory=uuid4)
                taken_at: datetime
            """
        ),
        encoding="utf-8",
    )
    config = Config(
        output=pkg / "_generated.py",
        modules=("models",),
        projections=(),
        root=tmp_path,
    )
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))
    try:
        (pkg / "_generated.py").write_text(generate(config), encoding="utf-8")
    finally:
        sys.path.remove(str(pkg))
        sys.modules.pop("models", None)
        sys.modules.pop("_generated", None)

    (pkg / "consumer.py").write_text(
        textwrap.dedent(
            """
            from datetime import datetime
            from _generated import ShotRef

            def good(s: ShotRef) -> datetime:
                return s.taken_at

            def bad(s: ShotRef) -> object:
                return s.does_not_exist
            """
        ),
        encoding="utf-8",
    )
    (pkg / "pyrightconfig.json").write_text(
        '{ "typeCheckingMode": "strict" }', encoding="utf-8"
    )
    pyright_cmd = (
        [sys.executable, "-m", "pyright"]
        if importlib.util.find_spec("pyright") is not None
        else [shutil.which("pyright") or "pyright"]
    )
    result = subprocess.run(
        [*pyright_cmd, "--pythonpath", sys.executable, "."],
        cwd=pkg,
        capture_output=True,
        text=True,
    )
    # exactly the bad-attribute access is flagged; the typed field is fine
    assert "does_not_exist" in result.stdout
    assert "taken_at" not in result.stdout
