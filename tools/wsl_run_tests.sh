#!/usr/bin/env bash
# Run the full Python test suite (incl. pty-based integration tests) and the
# firmware native tests. Intended for WSL/Linux, where the integration tests
# do not skip. Writes pytest output to /tmp/kneespa_pytest.log.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "=== pytest (full suite) ==="
python3 -m pytest -q >/tmp/kneespa_pytest.log 2>&1
PYTEST_EXIT=$?
tail -n 5 /tmp/kneespa_pytest.log | grep -E "passed|failed|error" || tail -n 5 /tmp/kneespa_pytest.log

echo "=== firmware native tests ==="
bash main/motor/run_native_tests.sh >/tmp/kneespa_fw.log 2>&1
FW_EXIT=$?
grep -E "Tests [0-9]+ Failures|All firmware|FAILURES" /tmp/kneespa_fw.log

echo "pytest_exit=$PYTEST_EXIT firmware_exit=$FW_EXIT"
exit $((PYTEST_EXIT || FW_EXIT))
