import json
from pathlib import Path

import pytest

from pipebridge.librarybody import Resolver, LIBRARY_CALL_DEPTH_CAP
from pipebridge.librarymap import load_library_map


def make_lib(tmp_path, name="build-lib"):
    root = tmp_path / name
    (root / "vars").mkdir(parents=True)
    (tmp_path / "library-map.json").write_text(
        json.dumps({"schema_version": 1, "libraries": {name: {"path": name}}}),
        encoding="utf-8",
    )
    return root, load_library_map(tmp_path / "library-map.json")


def write(root, name, text):
    p = root / "vars" / f"{name}.groovy"
    p.write_text(text, encoding="utf-8")
    return p


def test_expand_literal_and_forward(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", (
        "def call(String label) { packageSources(label) }\n"
        "def packageSources(String label) { sh \"echo $label\" }\n"
    ))
    r = Resolver(lm).resolve("build-lib", "publish", ["packaged"])
    assert not r.blocked
    assert [o.kind for o in r.operations] == ["sh"]
    assert r.operations[0].bindings == {"label": "packaged"}


def test_depth_first_source_order(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", (
        "def call() { a(); sh 'mid'; b() }\n"
        "def a() { sh 'a' }\n"
        "def b() { sh 'b' }\n"
    ))
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert [o.text for o in r.operations if o.kind == "sh"] == ["a", "mid", "b"]


def test_repeated_calls_no_shared_state(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", (
        "def call() { use('one'); use('two') }\n"
        "def use(String x) { sh \"v=$x\" }\n"
    ))
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert [o.bindings["x"] for o in r.operations] == ["one", "two"]


def test_missing_definition(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { nope() }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked
    assert any("has no definition" in f.message for f in r.findings)


def test_arg_count_mismatch(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call(String a) { helper() }\ndef helper(String x, String y) { sh 'x' }\n")
    r = Resolver(lm).resolve("build-lib", "publish", ["v"])
    assert r.blocked
    assert any("passed 0 argument(s)" in f.message for f in r.findings)


def test_recursion(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { call() }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked
    assert any("cycle" in f.message for f in r.findings)


def test_depth_limit(tmp_path):
    root, lm = make_lib(tmp_path)
    # chain a0 -> a1 -> ... -> a20 -> a21
    lines = ["def call() { a0() }\n"]
    for i in range(LIBRARY_CALL_DEPTH_CAP + 1):
        lines.append(f"def a{i}() {{ a{i+1}() }}\n")
    write(root, "publish", "".join(lines))
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked
    assert any("depth exceeded" in f.message for f in r.findings)


def test_newline_before_brace(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call()\n{ sh 'ok' }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert not r.blocked
    assert r.operations[0].text == "ok"


def test_braces_and_semicolons_in_strings(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { sh 'echo } ; {' }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert not r.blocked
    assert r.operations[0].text == "echo } ; {"


def test_unknown_closure_opaque(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { if (x) { sh 'inner' } }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked


def test_malformed_signature_not_resolvable(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call(String a,) { sh 'x' }\n")
    r = Resolver(lm).resolve("build-lib", "publish", ["v"])
    assert r.blocked


def test_pending_credentials_stash_unstash(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { withCredentials([]) { sh 'x' }\nstash name: 'd', includes: '**'\nunstash 'd'\n}\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    kinds = [o.kind for o in r.operations]
    assert "with-credentials" in kinds
    assert "stash" in kinds
    assert "unstash" in kinds
    assert all(o.pending for o in r.operations)


def test_transactional_zero_ops_on_later_failure(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { sh 'ok'; nope() }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked
    assert r.operations == []


def test_trailing_after_sh_rejected(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { sh 'ok' 'extra' }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked
    assert any("trailing tokens" in f.message for f in r.findings)


def test_trailing_after_helper_call_rejected(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { helper() } extra\n")
    # 'extra' at top level of body; but attached closure/trailing should block
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked


def test_missing_comma_in_call(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { helper('a' 'b') }\ndef helper(String a, String b) { sh 'x' }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked
    assert any("missing a comma" in f.message for f in r.findings)


def test_trailing_comma_in_call(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { helper('a',) }\ndef helper(String a) { sh 'x' }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked
    assert any("trailing comma" in f.message for f in r.findings)


def test_missing_closing_paren(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { helper('a' }\ndef helper(String a) { sh 'x' }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked


def test_malformed_nested_definition(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { helper() }\ndef helper(String a,) { sh 'x' }\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert r.blocked
    assert any("invalid parameter list" in f.message for f in r.findings)


def test_duplicate_vars_across_libraries(tmp_path):
    (tmp_path / "a" / "vars").mkdir(parents=True)
    (tmp_path / "b" / "vars").mkdir(parents=True)
    for name in ("a", "b"):
        (tmp_path / name / "vars" / "publish.groovy").write_text("def call() { sh 'x' }\n", encoding="utf-8")
    (tmp_path / "library-map.json").write_text(json.dumps({
        "schema_version": 1,
        "libraries": {"a": {"path": "a"}, "b": {"path": "b"}},
    }), encoding="utf-8")
    lm = load_library_map(tmp_path / "library-map.json")
    r = Resolver(lm).resolve("a", "publish", [])
    assert r.blocked
    assert any("more than one loaded library" in f.message for f in r.findings)


def test_pending_not_executable(tmp_path):
    root, lm = make_lib(tmp_path)
    write(root, "publish", "def call() { sh 'ok'\nstash name: 'd', includes: '**'\n}\n")
    r = Resolver(lm).resolve("build-lib", "publish", [])
    assert not r.executable
    assert r.pending


def test_containment_root_raises(tmp_path, tmp_path_factory):
    root, lm = make_lib(tmp_path)
    outside = tmp_path_factory.mktemp("outside")
    (outside / "publish.groovy").write_text("def call() { sh 'secret' }\n", encoding="utf-8")
    (root / "vars" / "publish.groovy").symlink_to(outside / "publish.groovy")
    from pipebridge.librarybody import LibraryResolutionError
    with pytest.raises(LibraryResolutionError):
        Resolver(lm).resolve("build-lib", "publish", [])
