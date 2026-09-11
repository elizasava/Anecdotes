from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from common import canonical_choice, load_config, load_yaml, normalize, risk_files

RISK_KEY_RE = re.compile(r"^RISK-\d{3,}$")
REQUIRED_TEXT_FIELDS = (
    "risk_name",
    "risk_event_description",
    "domain",
    "context_background",
    "impacted_assets",
)


def validate_risk(data: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    cfg = load_config()
    where = f" in {path}" if path else ""

    key = data.get("risk_key")
    if not isinstance(key, str) or not RISK_KEY_RE.fullmatch(key.strip().upper()):
        raise ValueError(f"risk_key{where} must look like RISK-001")
    data["risk_key"] = key.strip().upper()

    for field in REQUIRED_TEXT_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field}{where} is required and must be non-empty text")
        data[field] = value.strip()

    brands = data.get("uki_brand")
    if not isinstance(brands, list) or not brands or not all(isinstance(x, str) and x.strip() for x in brands):
        raise ValueError(f"uki_brand{where} must be a non-empty YAML list of names")

    canonical_brands = [canonical_choice(x, cfg["allowed_uki_brands"], "UKI Brand") for x in brands]
    if len({normalize(x) for x in canonical_brands}) != len(canonical_brands):
        raise ValueError(f"uki_brand{where} contains duplicates")
    data["uki_brand"] = canonical_brands
    data["domain"] = canonical_choice(data["domain"], cfg["allowed_domains"], "Domain")
    return data


def load_risk(path: Path) -> dict[str, Any]:
    return validate_risk(load_yaml(path), path)


def validate_all_risks() -> list[Path]:
    seen: dict[str, Path] = {}
    files = risk_files()
    for path in files:
        data = load_risk(path)
        key = data["risk_key"]
        if key in seen:
            raise ValueError(f"Duplicate risk_key {key}: {seen[key]} and {path}")
        seen[key] = path
    return files
