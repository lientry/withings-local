# Releasing

HACS offers updates from GitHub releases. A release is created automatically when a `vX.Y.Z` tag is pushed (`.github/workflows/release.yml`).

1. Pick the version, following [semver](https://semver.org): a bug fix bumps the patch version, a feature the minor version, a breaking change the major version.
2. Set it in **both** `custom_components/withings_local/manifest.json` (`"version"`) and `pyproject.toml`. A test fails if they differ.
3. In `CHANGELOG.md`, move the entries under `## [Unreleased]` to a new `## [X.Y.Z] - YYYY-MM-DD` section.
4. If the library changed, run `uv run tools/bundle_lib.py`, then `uv run pytest`.
5. Commit, tag and push:
   ```bash
   git commit -am "Release vX.Y.Z"
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main vX.Y.Z
   ```
6. The release workflow checks that the tag matches the manifest, runs the tests, and publishes a GitHub release with the changelog section as its notes.
