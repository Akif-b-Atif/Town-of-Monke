"""FIX-2 and FIX-3: one version source, and the invite permissions integer in the README."""
import pathlib
import re

import check
import monke

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_permissions_integer_matches_readme():
    assert check.PERMISSIONS.value == 2416045072
    assert str(check.PERMISSIONS.value) in (ROOT / "README.md").read_text(encoding="utf-8")
    assert check.PERMISSIONS.attach_files


def test_version_has_a_single_source():
    toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^dynamic\s*=\s*\["version"\]', toml, re.M)
    assert not re.search(r'^version\s*=\s*"\d', toml, re.M)  # no hard-coded copy
    assert re.fullmatch(r"\d+\.\d+\.\d+", monke.__version__)


def test_readme_does_not_hard_code_a_version():
    first = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]
    assert not re.search(r"\d+\.\d+\.\d+", first)
