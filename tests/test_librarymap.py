import json
from pathlib import Path

import pytest

from pipebridge.librarymap import LibraryMapError, load_library_map


def make_map(tmp_path, obj):
    p = tmp_path / "library-map.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_valid_map(tmp_path):
    lib = tmp_path / "build-lib"
    (lib / "vars").mkdir(parents=True)
    m = make_map(tmp_path, {"schema_version": 1, "libraries": {"build-lib": {"path": "build-lib"}}})
    lm = load_library_map(m)
    assert "build-lib" in lm.entries
    assert lm.entries["build-lib"].root == (tmp_path / "build-lib").resolve()


def test_duplicate_keys(tmp_path):
    p = tmp_path / "m.json"
    p.write_text('{"schema_version": 1, "libraries": {}, "schema_version": 1}', encoding="utf-8")
    with pytest.raises(LibraryMapError):
        load_library_map(p)


def test_invalid_name(tmp_path):
    lib = tmp_path / "build-lib"
    (lib / "vars").mkdir(parents=True)
    m = make_map(tmp_path, {"schema_version": 1, "libraries": {"1bad": {"path": "build-lib"}}})
    with pytest.raises(LibraryMapError):
        load_library_map(m)


def test_absolute_path(tmp_path):
    lib = tmp_path / "build-lib"
    (lib / "vars").mkdir(parents=True)
    m = make_map(tmp_path, {"schema_version": 1, "libraries": {"build-lib": {"path": "/abs"}}})
    with pytest.raises(LibraryMapError):
        load_library_map(m)


def test_traversal(tmp_path):
    lib = tmp_path / "build-lib"
    (lib / "vars").mkdir(parents=True)
    m = make_map(tmp_path, {"schema_version": 1, "libraries": {"build-lib": {"path": "../x"}}})
    with pytest.raises(LibraryMapError):
        load_library_map(m)


def test_control_char(tmp_path):
    lib = tmp_path / "build-lib"
    (lib / "vars").mkdir(parents=True)
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"schema_version": 1, "libraries": {"build-lib": {"path": "build-lib"}}}), encoding="utf-8")
    # inject control char via raw
    raw = '{"schema_version": 1, "libraries": {"build-lib": {"path": "build\\u0001lib"}}}'
    m.write_text(raw, encoding="utf-8")
    with pytest.raises(LibraryMapError):
        load_library_map(m)


def test_missing_vars(tmp_path):
    lib = tmp_path / "build-lib"
    lib.mkdir()
    m = make_map(tmp_path, {"schema_version": 1, "libraries": {"build-lib": {"path": "build-lib"}}})
    with pytest.raises(LibraryMapError):
        load_library_map(m)


def test_symlink_escape(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "vars").mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside)
    m = make_map(tmp_path, {"schema_version": 1, "libraries": {"build-lib": {"path": "link"}}})
    with pytest.raises(LibraryMapError):
        load_library_map(m)


def test_missing_file(tmp_path):
    m = tmp_path / "nope.json"
    with pytest.raises(LibraryMapError):
        load_library_map(m)


def test_deterministic_ordering(tmp_path):
    for name in ("b", "a"):
        (tmp_path / name / "vars").mkdir(parents=True)
    m = make_map(tmp_path, {"schema_version": 1, "libraries": {"b": {"path": "b"}, "a": {"path": "a"}}})
    lm = load_library_map(m)
    assert list(lm.entries.keys()) == ["a", "b"]

def _lib(tmp_path, name="build-lib"):
    lib = tmp_path / name
    (lib / "vars").mkdir(parents=True)
    return lib

@pytest.mark.parametrize("version", [True, False, 1.0, "1", None, 2, 0])
def test_schema_version_type(tmp_path, version):
    _lib(tmp_path)
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"schema_version": version, "libraries": {}}), encoding="utf-8")
    with pytest.raises(LibraryMapError):
        load_library_map(m)

@pytest.mark.parametrize("raw", ["./build-lib", "build-lib/.", "build-lib//", "build-lib/", ".", ".."])
def test_raw_path_segments(tmp_path, raw):
    _lib(tmp_path)
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"schema_version": 1, "libraries": {"build-lib": {"path": raw}}}), encoding="utf-8")
    with pytest.raises(LibraryMapError):
        load_library_map(m)

def test_del_char(tmp_path):
    _lib(tmp_path)
    m = tmp_path / "m.json"
    m.write_text('{"schema_version": 1, "libraries": {"build-lib": {"path": "build-lib\u007f"}}}', encoding="utf-8")
    with pytest.raises(LibraryMapError):
        load_library_map(m)

def test_nested_duplicate_keys(tmp_path):
    _lib(tmp_path)
    m = tmp_path / "m.json"
    m.write_text('{"schema_version": 1, "libraries": {"build-lib": {"path": "build-lib", "path": "build-lib"}}}', encoding="utf-8")
    with pytest.raises(LibraryMapError):
        load_library_map(m)

def test_invalid_json(tmp_path):
    m = tmp_path / "m.json"
    m.write_text("{not json", encoding="utf-8")
    with pytest.raises(LibraryMapError):
        load_library_map(m)

def test_unknown_schema_keys(tmp_path):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"schema_version": 1, "libraries": {}, "extra": 1}), encoding="utf-8")
    with pytest.raises(LibraryMapError):
        load_library_map(m)

def test_wrong_entry_type(tmp_path):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"schema_version": 1, "libraries": {"build-lib": "build-lib"}}), encoding="utf-8")
    with pytest.raises(LibraryMapError):
        load_library_map(m)

def test_map_path_is_directory(tmp_path):
    d = tmp_path / "dir"
    d.mkdir()
    with pytest.raises(LibraryMapError):
        load_library_map(d)
