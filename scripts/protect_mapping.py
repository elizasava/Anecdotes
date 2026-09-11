from __future__ import annotations

import argparse
import subprocess
import sys

from common import ROOT

MAP_FILE = "system/anecdotes-risk-map.yaml"


def mapping_changed(base_ref: str) -> bool:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD", "--", MAP_FILE],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return bool(proc.stdout.strip())


def is_allowed(author: str, head_ref: str, allowed_bot: str) -> bool:
    return author == allowed_bot and (
        head_ref == "automation/anecdotes-map" or head_ref.startswith("automation/anecdotes-map-")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--author", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--allowed-bot", required=True)
    args = parser.parse_args()

    if not mapping_changed(args.base_ref):
        print("Mapping file not changed.")
        return 0
    if not is_allowed(args.author, args.head_ref, args.allowed_bot):
        print(
            f"BLOCKED: {MAP_FILE} is machine-managed. Only {args.allowed_bot} on an "
            "automation/anecdotes-map branch (or legacy automation/anecdotes-map-* branch) may change it.",
            file=sys.stderr,
        )
        return 1
    print("Machine-generated mapping change accepted for review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
