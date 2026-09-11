from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from anecdotes_client import AnecdotesClient, AnecdotesError, FieldResolver
from common import MAP_PATH, ROOT, load_config
from github_pending import pending_mapping_keys
from mapping import get_mapping, set_mapping
from risk_io import load_risk


def find_first_string(payload: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = find_first_string(value, keys)
            if found:
                return found
    return None


def build_payload(risk: dict[str, Any], cfg: dict[str, Any], resolver: FieldResolver) -> dict[str, Any]:
    fn = cfg["field_names"]
    field_values = {
        fn["uki_brand"]: risk["uki_brand"],
        fn["risk_event_description"]: risk["risk_event_description"],
        fn["domain"]: risk["domain"],
        fn["context_background"]: risk["context_background"],
        fn["impacted_assets"]: risk["impacted_assets"],
    }
    encoded: dict[str, str | list[str]] = {}
    for field_name, value in field_values.items():
        field_id, encoded_value = resolver.encode(field_name, value)
        encoded[field_id] = encoded_value
    return {"name": risk["risk_name"], "fields": encoded}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/update merged GitHub risks in Anecdotes")
    parser.add_argument("--files", nargs="+", required=True, help="Changed risk YAML files")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--check-connection",
        action="store_true",
        help="In dry-run mode, also validate Anecdotes auth and custom-field metadata fetch.",
    )
    args = parser.parse_args()

    cfg = load_config()
    placeholder = "PASTE_YOUR_ANECDOTES_REGISTER_ID_HERE"
    if placeholder in str(cfg.get("register_id", "")):
        print("CONFIG ERROR: replace the red register_id placeholder in config/anecdotes.yaml", file=sys.stderr)
        return 2

    api_key = os.getenv("ANECDOTES", "")
    ui_url = os.getenv("ANECDOTES_URL", "").strip()
    print(f"Target register_id: {cfg['register_id']}")
    if ui_url:
        print(f"Target Anecdotes URL: {ui_url}")

    if (not args.dry_run or args.check_connection) and not api_key:
        print("SECRET ERROR: GitHub secret/environment variable ANECDOTES is required", file=sys.stderr)
        return 2

    risks: list[tuple[Path, dict[str, Any]]] = []
    for raw in args.files:
        path = (ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        if not path.exists():
            print(f"Skipping deleted/nonexistent file {raw}; this integration never deletes Anecdotes risks.")
            continue
        if ROOT not in path.parents:
            raise ValueError(f"Refusing path outside repository: {path}")
        risks.append((path, load_risk(path)))

    if not risks:
        print("No existing changed risk files to sync.")
        return 0

    if args.dry_run:
        if args.check_connection:
            client = AnecdotesClient(
                api_key=api_key,
                api_base_url=cfg["api_base_url"],
                auth_exchange_url=cfg["auth_exchange_url"],
                user_agent=cfg.get("user_agent", "github-anecdotes-risk-sync/1.0"),
            )
            resolver = FieldResolver(client.get_custom_fields())
            print(f"DRY RUN: connection OK; discovered {len(resolver.definitions)} custom fields")
        for path, risk in risks:
            action = "UPDATE" if get_mapping(risk["risk_key"]) else "CREATE"
            print(f"DRY RUN: {action} {risk['risk_key']} from {path.relative_to(ROOT)}")
        return 0

    client = AnecdotesClient(
        api_key=api_key,
        api_base_url=cfg["api_base_url"],
        auth_exchange_url=cfg["auth_exchange_url"],
        user_agent=cfg.get("user_agent", "github-anecdotes-risk-sync/1.0"),
    )
    resolver = FieldResolver(client.get_custom_fields())
    pending = pending_mapping_keys()
    created_keys: list[str] = []

    for path, risk in risks:
        key = risk["risk_key"]
        payload = build_payload(risk, cfg, resolver)
        mapping = get_mapping(key)
        if mapping:
            internal_id = mapping.get("anecdotes_internal_id")
            if not internal_id:
                raise ValueError(f"Mapping for {key} is missing anecdotes_internal_id")
            client.update_risk(internal_id, payload)
            print(f"UPDATED {key} -> {internal_id}")
            continue

        if key in pending:
            raise RuntimeError(
                f"{key} already has a pending automated mapping PR. Refusing to CREATE again. "
                "Merge/close that mapping PR first."
            )

        create_payload = dict(payload)
        create_payload["register_id"] = cfg["register_id"]
        result = client.create_risk(create_payload)
        internal_id = find_first_string(result, ("id", "risk_id", "riskId"))
        customer_risk_id = find_first_string(result, ("customer_risk_id", "customerRiskId"))
        if not internal_id or not internal_id.startswith("risk_"):
            raise AnecdotesError(
                "Risk was created but the response did not expose the expected internal risk_... id. "
                "STOP: inspect this run before retrying to avoid a duplicate."
            )
        set_mapping(key, internal_id, customer_risk_id, str(path.relative_to(ROOT)))
        created_keys.append(key)
        print(f"CREATED {key} -> {internal_id}")

    sync_dir = ROOT / ".sync"
    sync_dir.mkdir(exist_ok=True)
    metadata = {
        "mapping_changed": bool(created_keys),
        "created_keys": created_keys,
        "mapping_path": str(MAP_PATH.relative_to(ROOT)),
    }
    (sync_dir / "result.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    if created_keys:
        marker = ",".join(created_keys)
        body = (
            "Automated Anecdotes ID mapping update.\n\n"
            "This PR contains machine-generated technical IDs only. Do not hand-edit them.\n\n"
            f"<!-- anecdotes-risk-keys: {marker} -->\n"
        )
        (sync_dir / "mapping_pr_body.md").write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"SYNC FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
