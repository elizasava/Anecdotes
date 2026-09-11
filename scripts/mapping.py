from __future__ import annotations

from typing import Any

from common import MAP_PATH, load_yaml, save_yaml


def load_map() -> dict[str, Any]:
    data = load_yaml(MAP_PATH)
    if data.get("version") != 1:
        raise ValueError("Unsupported mapping file version")
    risks = data.get("risks")
    if not isinstance(risks, dict):
        raise ValueError("system/anecdotes-risk-map.yaml must contain a 'risks' object")
    return data


def get_mapping(risk_key: str) -> dict[str, str] | None:
    entry = load_map()["risks"].get(risk_key)
    return entry if isinstance(entry, dict) else None


def set_mapping(risk_key: str, internal_id: str, customer_risk_id: str | None, source_file: str) -> None:
    data = load_map()
    data["risks"][risk_key] = {
        "anecdotes_internal_id": internal_id,
        "anecdotes_risk_id": customer_risk_id or "",
        "source_file": source_file,
    }
    save_yaml(MAP_PATH, data)
