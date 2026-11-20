import json
from pathlib import Path

import pytest

from pipebridge.librarymap import LibraryMap, LibraryEntry, load_library_map
from pipebridge.libraryresolver import (
    LibraryParseError,
    load_var,
    discover_vars,
)


def make_map(tmp_path, libs):
    base = tmp_path / "map"
    base.mkdir()
    (tmp_path / "library-map.json").write_text(json.dumps(libs), encoding="utf-8")
    return load_library_map(tmp_path / "library-map.json")


def make_lib(tmp_path, name="build-lib"):
    root = tmp_path / name
    (root / "vars").mkdir(parents=True)
    return root


def test_parse_call_and_helper(tmp_path):
    root = make_lib(tmp_path)
    (root / "vars" / "publish.groovy").write_text(
        "def call(String label) { packageSources(label) }\n"
        "def packageSources(String label) { sh 'echo $label' }\n",
        encoding="utf-8",
    )
    var = load_var(root / "vars" / "publish.groovy", root)
    assert var.call is not None
    assert var.call.params[0].name == "label"
    assert len(var.definitions) == 2
    assert var.findings == []


def test_no_call(tmp_path):
    root = make_lib(tmp_path)
    (root / "vars" / "publish.groovy").write_text("def helper() { sh 'x' }\n", encoding="utf-8")
    var = load_var(root / "vars" / "publish.groovy", root)
    assert any("no call()" in f.message for f in var.findings)


def test_duplicate_call(tmp_path):
    root = make_lib(tmp_path)
    (root / "vars" / "publish.groovy").write_text(
        "def call() { sh 'x' }\ndef call() { sh 'y' }\n", encoding="utf-8"
    )
    var = load_var(root / "vars" / "publish.groovy", root)
    assert any("more than one call()" in f.message for f in var.findings)


def test_duplicate_params(tmp_path):
    root = make_lib(tmp_path)
    (root / "vars" / "publish.groovy").write_text(
        "def call(String a, String a) { sh 'x' }\n", encoding="utf-8"
    )
    var = load_var(root / "vars" / "publish.groovy", root)
    assert any("duplicate parameter" in f.message for f in var.findings)


def test_escaping_symlink_rejected_before_read(tmp_path, tmp_path_factory):
    root = make_lib(tmp_path)
    outside = tmp_path_factory.mktemp("outside")
    secret = outside / "secret.groovy"
    secret.write_text("def call() { sh 'secret' }\n", encoding="utf-8")
    link = root / "vars" / "publish.groovy"
    link.symlink_to(secret)
    with pytest.raises(LibraryParseError):
        load_var(link, root)


def test_unused_file_not_opened(tmp_path):
    root = make_lib(tmp_path)
    # Unused file that would raise if opened outside root; discovery must not read it.
    bad = root / "vars" / "unused.groovy"
    bad.write_text("not valid {", encoding="utf-8")
    m = make_map(tmp_path, {"schema_version": 1, "libraries": {"build-lib": {"path": "build-lib"}}})
    disc, findings = discover_vars(m)
    assert any(d.name == "unused" for d in disc)
    assert findings == []


def test_shadowing(tmp_path):
    root = make_lib(tmp_path)
    (root / "vars" / "sh.groovy").write_text("def call() { sh 'x' }\n", encoding="utf-8")
    m = make_map(tmp_path, {"schema_version": 1, "libraries": {"build-lib": {"path": "build-lib"}}})
    _, findings = discover_vars(m)
    assert any("shadows a built-in step" in f.message for f in findings)


def test_duplicate_across_libraries(tmp_path):
    r1 = make_lib(tmp_path, "a")
    r2 = make_lib(tmp_path, "b")
    for r in (r1, r2):
        (r / "vars" / "publish.groovy").write_text("def call() { sh 'x' }\n", encoding="utf-8")
    m = make_map(tmp_path, {
        "schema_version": 1,
        "libraries": {"a": {"path": "a"}, "b": {"path": "b"}},
    })
    _, findings = discover_vars(m)
    assert any("more than one loaded library" in f.message for f in findings)


def test_braces_in_strings_and_comments_do_not_break(tmp_path):
    root = make_lib(tmp_path)
    (root / "vars" / "publish.groovy").write_text(
        "def call() { sh 'echo } { ;' // }\n\n}\n", encoding="utf-8"
    )
    var = load_var(root / "vars" / "publish.groovy", root)
    assert var.call is not None


def test_params_strict_cases(tmp_path):
    root = make_lib(tmp_path)
    cases = [
        "def call(String a, String b) { sh 'x' }\n",  # valid multiline-ish
        "def call(String a, def b) { sh 'x' }\n",
        "def call(String a,, String b) { sh 'x' }\n",
        "def call(String a,) { sh 'x' }\n",
        "def call(String a = 'x') { sh 'x' }\n",
        "def call(int a) { sh 'x' }\n",
        "def call(String a + b) { sh 'x' }\n",
    ]
    valid = [0]
    for idx, src in enumerate(cases):
        p = root / "vars" / f"v{idx}.groovy"
        p.write_text(src, encoding="utf-8")
        var = load_var(p, root)
        if idx in valid:
            assert var.call is not None
            assert [x.name for x in var.call.params] == ["a", "b"]
        else:
            assert any("invalid parameter list" in f.message for f in var.findings)


def test_multiline_params(tmp_path):
    root = make_lib(tmp_path)
    p = root / "vars" / "publish.groovy"
    p.write_text("def call(\n  String label,\n  String other\n) { sh 'x' }\n", encoding="utf-8")
    var = load_var(p, root)
    assert var.call is not None
    assert [x.name for x in var.call.params] == ["label", "other"]


def test_duplicate_helper_position(tmp_path):
    root = make_lib(tmp_path)
    p = root / "vars" / "publish.groovy"
    p.write_text("def call() { helper() }\ndef helper() { sh 'a' }\ndef helper() { sh 'b' }\n", encoding="utf-8")
    var = load_var(p, root)
    dup = [f for f in var.findings if "duplicate definition 'helper'" in f.message]
    assert len(dup) == 1
    assert dup[0].line == 3


def test_lexer_error_converted(tmp_path):
    root = make_lib(tmp_path)
    p = root / "vars" / "publish.groovy"
    p.write_text("def call() { sh 'unterminated }\n", encoding="utf-8")
    var = load_var(p, root)
    assert any(f.code == "PB-LIB-CALL" and "cannot be read" in f.message for f in var.findings)


def test_unused_symlink_not_followed(tmp_path, tmp_path_factory):
    root = make_lib(tmp_path)
    outside = tmp_path_factory.mktemp("out")
    (outside / "secret.groovy").write_text("def call() { sh 'secret' }\n", encoding="utf-8")
    (root / "vars" / "escaping.groovy").symlink_to(outside / "secret.groovy")
    (root / "vars" / "dangling.groovy").symlink_to(root / "vars" / "nope.groovy")
    m = make_map(tmp_path, {"schema_version": 1, "libraries": {"build-lib": {"path": "build-lib"}}})
    disc, findings = discover_vars(m)
    names = [d.name for d in disc]
    assert "escaping" not in names
    assert "dangling" not in names
