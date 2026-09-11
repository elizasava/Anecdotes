from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from common import ROOT
from risk_io import validate_all_risks


def deleted_active_risks(base_ref: str | None) -> list[str]:
    if not base_ref:
        return []
    proc = subprocess.run(
        ["git", "diff", "--diff-filter=D", "--name-only", f"{base_ref}...HEAD", "--", "risks/active/*.yaml"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", help="e.g. origin/main. Used to block risk YAML deletion.")
    args = parser.parse_args()
    try:
        files = validate_all_risks()
        deleted = deleted_active_risks(args.base_ref)
        if deleted:
            raise ValueError(
                "Risk deletion is intentionally disabled. Do not delete mapped risk YAML files. "
                f"Deleted: {', '.join(deleted)}"
            )
        print(f"Validated {len(files)} risk file(s).")
        return 0
    except Exception as exc:
        print(f"VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
