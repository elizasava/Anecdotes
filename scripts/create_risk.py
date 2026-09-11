from __future__ import annotations

import re

from common import RISKS_DIR, canonical_choice, load_config, save_yaml


KEY_STEM_RE = re.compile(r"^RISK-(\d+)$", re.IGNORECASE)


def next_key() -> str:
    highest = 0
    for path in RISKS_DIR.glob("*.yaml"):
        match = KEY_STEM_RE.fullmatch(path.stem)
        if not match:
            continue
        highest = max(highest, int(match.group(1)))
    return f"RISK-{highest + 1:03d}"


def choose_one(title: str, values: list[str]) -> str:
    print(f"\n{title}:")
    for i, value in enumerate(values, 1):
        print(f"  {i}. {value}")
    while True:
        raw = input("Choose number or type the name: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(values):
            return values[int(raw) - 1]
        try:
            return canonical_choice(raw, values, title)
        except ValueError as exc:
            print(exc)


def choose_many(title: str, values: list[str]) -> list[str]:
    print(f"\n{title} (one or more):")
    for i, value in enumerate(values, 1):
        print(f"  {i}. {value}")
    while True:
        raw = input("Choose numbers separated by commas, or type names separated by commas: ").strip()
        parts = [x.strip() for x in raw.split(",") if x.strip()]
        try:
            result: list[str] = []
            for part in parts:
                if part.isdigit() and 1 <= int(part) <= len(values):
                    result.append(values[int(part) - 1])
                else:
                    result.append(canonical_choice(part, values, title))
            if result:
                return list(dict.fromkeys(result))
        except ValueError as exc:
            print(exc)


def required(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("This field is required.")


def main() -> None:
    cfg = load_config()
    key = next_key()
    data = {
        "risk_key": key,
        "risk_name": required("Risk name: "),
        "uki_brand": choose_many("UKI Brand", cfg["allowed_uki_brands"]),
        "risk_event_description": required("Risk event description: "),
        "domain": choose_one("Domain", cfg["allowed_domains"]),
        "context_background": required("Context/background: "),
        "impacted_assets": required("Impacted asset/s: "),
    }
    path = RISKS_DIR / f"{key}.yaml"
    save_yaml(path, data)
    print(f"\nCreated {path}")
    print("Review/edit it, then create a PR. Matching is case-insensitive during validation and sync.")


if __name__ == "__main__":
    main()
