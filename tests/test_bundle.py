"""The integration's bundled library must match src/withings_wpp (run tools/bundle_lib.py)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "withings_wpp"
BUNDLED = ROOT / "custom_components" / "withings_local" / "withings_wpp"


def test_bundled_library_is_in_sync():
    src = {p.name: p.read_bytes() for p in SRC.glob("*.py")}
    bundled = {p.name: p.read_bytes() for p in BUNDLED.glob("*.py")}
    stale = sorted(n for n in src.keys() | bundled.keys() if src.get(n) != bundled.get(n))
    assert not stale, f"bundled copy is stale: {stale}; run `uv run tools/bundle_lib.py`"
