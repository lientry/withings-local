"""The integration (what HA and HACS show) and the library must carry the same version."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_versions_match():
    manifest = json.loads((ROOT / "custom_components" / "withings_local" / "manifest.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert manifest["version"] == project["version"]


def test_changelog_has_current_version():
    version = json.loads((ROOT / "custom_components" / "withings_local" / "manifest.json").read_text())["version"]
    assert f"## [{version}]" in (ROOT / "CHANGELOG.md").read_text()
