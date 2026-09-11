from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "anecdotes.yaml"
MAP_PATH = ROOT / "system" / "anecdotes-risk-map.yaml"
RISKS_DIR = ROOT / "risks" / "active"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping/object")
    return data


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=1000)


def load_config() -> dict[str, Any]:
    return load_yaml(CONFIG_PATH)


def normalize(value: str) -> str:
    """Case-insensitive, whitespace-tolerant comparison key."""
    value = value.strip().casefold()
    return re.sub(r"\s+", " ", value)


def canonical_choice(value: str, allowed: list[str], label: str) -> str:
    by_norm = {normalize(item): item for item in allowed}
    key = normalize(value)
    if key not in by_norm:
        raise ValueError(f"Invalid {label}: {value!r}. Allowed: {', '.join(allowed)}")
    return by_norm[key]


def risk_files() -> list[Path]:
    return sorted(p for p in RISKS_DIR.glob("*.yaml") if p.is_file())
