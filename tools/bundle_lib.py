"""Copy the withings_wpp library into the Home Assistant integration.

Usage: uv run tools/bundle_lib.py

The integration ships its own copy of the library so it installs through HACS with no PyPI
package. src/withings_wpp is the source of truth; run this after changing it. A test fails when
the bundled copy is stale.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "withings_wpp"
DST = ROOT / "custom_components" / "withings_local" / "withings_wpp"


def main() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)
    for f in sorted(SRC.glob("*.py")):
        shutil.copy2(f, DST / f.name)
        print(f"bundled {f.name}")


if __name__ == "__main__":
    main()
