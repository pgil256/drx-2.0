# Development and deployment tooling

This directory stays on the PC/CI during routine device updates. It contains
documentation, Python tests, the firmware native-test harness, validation scripts,
GUI previews and hardware diagnostic tools, and the PC-side sync scripts.

Run `python -m pytest` from the repository root. Firmware tests run with
`bash development/tests/firmware/run_native_tests.sh`. See
[deployment.md](docs/deployment.md) for the device layout and sync workflow.

Diagnostic tools can be copied temporarily for a maintenance session; they are
not part of the normal device release.
