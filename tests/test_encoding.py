"""Windows reads text files with the legacy code page unless told otherwise (cp1252), and the README, the golden
file, flavour.yaml and the sources contain non-ASCII characters. Every text-mode file read or write in the project must
name its encoding. This test scans the code (no Windows machine needed) so the mistake cannot come back."""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNED = [*ROOT.joinpath("monke").rglob("*.py"), *ROOT.joinpath("tests").rglob("*.py"), ROOT / "check.py"]


def _mode(call: ast.Call) -> str:
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        return str(call.args[1].value)
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    return "r"


def _missing_encoding(path: pathlib.Path) -> list:
    bad = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        kind = None
        if isinstance(func, ast.Name) and func.id == "open":
            kind = "open" if "b" not in _mode(node) else None  # binary mode has no encoding
        elif isinstance(func, ast.Attribute) and func.attr in ("read_text", "write_text"):
            kind = func.attr
        if kind and not any(kw.arg == "encoding" for kw in node.keywords):
            bad.append(f"{path.relative_to(ROOT)}:{node.lineno} {kind}()")
    return bad


def test_every_text_file_access_names_its_encoding():
    bad = [b for p in SCANNED for b in _missing_encoding(p)]
    assert not bad, "pass encoding='utf-8' (Windows defaults to cp1252): " + ", ".join(bad)


def test_the_scanner_itself_catches_the_mistake(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("open('a')\nopen('b', 'rb')\nopen('c', encoding='utf-8')\np.read_text()\np.write_text('x', encoding='utf-8')\n",
                 encoding="utf-8")
    f.relative_to  # noqa: B018
    ROOT_BACKUP = globals()["ROOT"]
    globals()["ROOT"] = tmp_path
    try:
        assert [b.split(" ")[1] for b in _missing_encoding(f)] == ["open()", "read_text()"]
    finally:
        globals()["ROOT"] = ROOT_BACKUP
