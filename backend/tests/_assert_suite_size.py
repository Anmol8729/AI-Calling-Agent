"""Guards against the security suite silently disappearing.

Run by CI. A refactor that renames or empties test_security_contracts.py would
otherwise leave the pipeline green while every regression test was gone — the worst
possible failure mode for a suite whose whole job is to stop old holes reopening.
"""

import pathlib
import subprocess
import sys

MINIMUM = 50
TARGET = "backend/tests/test_security_contracts.py"

root = pathlib.Path(__file__).resolve().parents[2]

result = subprocess.run(
    [sys.executable, "-m", "pytest", TARGET, "--collect-only", "-q"],
    capture_output=True,
    text=True,
    cwd=root,
)
collected = sum(1 for line in result.stdout.splitlines() if "::" in line)
print(f"security contract tests collected: {collected}")

if collected < MINIMUM:
    print(result.stdout[-2000:])
    print(result.stderr[-2000:], file=sys.stderr)
    sys.exit(
        f"Expected at least {MINIMUM} security regression tests in {TARGET}, "
        f"found {collected}. If tests were intentionally removed, lower MINIMUM "
        "deliberately and say why in the commit message."
    )

print("Security suite is present.")
