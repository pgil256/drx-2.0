# Development and deployment tooling

This directory stays on the PC/CI during routine device updates. It contains
documentation, Python tests, the firmware native-test harness, validation scripts,
GUI previews and hardware diagnostic tools, and the PC-side sync scripts.

Run `python -m pytest` from the repository root. Firmware tests run with
`bash development/tests/firmware/run_native_tests.sh`. See
[deployment.md](docs/deployment.md) for the device layout and sync workflow.

Diagnostic tools can be copied temporarily for a maintenance session; they are
not part of the normal device release.

## Local workspace files

- `.cache/` at the repository root holds generated test output, previews, and caches.
  Pytest's result cache is configured there. For an explicit temporary directory,
  use `--basetemp=.cache/<run-name>` instead of creating a new root folder.
- `reference/local/` holds the PC's original mockups, assets, screenshots, and design exports.
- `backups/local/` holds local workspace backup archives.
- `devices/archive/` at the repository root preserves old device files after migration.

All four locations are ignored by Git. Keep durable documentation and reusable
tools in the tracked directories rather than inside the local archives.
For coverage output inside `.cache/`, use:

```bash
python -m pytest --cov=runtime/raspberry-pi/main --cov-config=development/coverage.ini
```
