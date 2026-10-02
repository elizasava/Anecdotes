#!/usr/bin/env python3
"""Local interactive CLI for creating and updating risks directly in Anecdotes.

Anecdotes is the source of truth for this CLI. It never reads or writes risk YAML,
the Anecdotes ID mapping file, or any other file in this repository, and it never
opens a pull request. The existing GitHub/YAML sync workflow is untouched.

Authentication, the register id, custom-field lookup, option resolution and the
retry/token-refresh behaviour are all reused from the existing integration.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from anecdotes_client import AnecdotesClient, AnecdotesError, FieldResolver, ReadOnlyModeError
from common import load_config, normalize
from sync_risks import build_payload, find_first_string

CUSTOM_FIELD_KEYS = (
    "uki_brand",
    "risk_event_description",
    "domain",
    "context_background",
    "impacted_assets",
)
SELECT_KEYS = ("uki_brand", "domain")
MULTI_SELECT_KEYS = ("uki_brand",)
CONFIG_OPTION_KEYS = {"uki_brand": "allowed_uki_brands", "domain": "allowed_domains"}

INTERNAL_ID_KEYS = ("id", "risk_id", "riskId", "internal_id", "internalId")
DISPLAY_ID_KEYS = ("customer_risk_id", "customerRiskId", "display_id", "displayId", "key")
NAME_KEYS = ("name", "risk_name", "riskName", "title")

DRY_RUN_BANNER = "DRY RUN - NO CHANGES WILL BE MADE"
DRY_RUN_FOOTER = "DRY RUN - NO CHANGES WERE MADE"
RULE = "-" * 32

STATUS_HINTS = {
    401: "Authentication failed or the token expired. Check the ANECDOTES environment variable.",
    403: "The token is valid but lacks permission for this register or operation.",
    404: "Anecdotes returned 'not found'. The risk or endpoint does not exist.",
    429: "Anecdotes rate-limited this client after retries. Wait and try again.",
}


class CliError(RuntimeError):
    """User-facing configuration or input problem; never contains credentials."""


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #


def require_api_key() -> str:
    api_key = os.getenv("ANECDOTES", "").strip()
    if not api_key:
        raise CliError(
            "Environment variable ANECDOTES is not set. "
            "Export your Anecdotes API token before running this CLI."
        )
    return api_key


def build_client(cfg: dict[str, Any], api_key: str, read_only: bool) -> AnecdotesClient:
    return AnecdotesClient(
        api_key=api_key,
        api_base_url=cfg["api_base_url"],
        auth_exchange_url=cfg["auth_exchange_url"],
        user_agent=cfg.get("user_agent", "github-anecdotes-risk-sync/1.0"),
        read_only=read_only,
    )


def check_register(cfg: dict[str, Any]) -> None:
    placeholder = "PASTE_YOUR_ANECDOTES_REGISTER_ID_HERE"
    if placeholder in str(cfg.get("register_id", "")):
        raise CliError("Replace the register_id placeholder in config/anecdotes.yaml first.")


# --------------------------------------------------------------------------- #
# Live option metadata
# --------------------------------------------------------------------------- #


def display_options(resolver: FieldResolver, field_name: str) -> list[str]:
    """Live option labels, with any 'CODE - ' prefix stripped for readability."""
    labels = resolver.option_labels(field_name)
    if not labels:
        raise CliError(
            f"Anecdotes returned no selectable options for custom field {field_name!r}. "
            "Cannot continue safely."
        )
    stripped = [label.split(" - ", 1)[1] if " - " in label else label for label in labels]
    if len({normalize(item) for item in stripped}) == len(labels):
        return stripped
    return labels


def warn_on_option_drift(resolver: FieldResolver, cfg: dict[str, Any]) -> None:
    for key in SELECT_KEYS:
        field_name = cfg["field_names"][key]
        live = display_options(resolver, field_name)
        known = [str(item) for item in cfg.get(CONFIG_OPTION_KEYS[key], [])]
        live_norm = {normalize(item) for item in live}
        known_norm = {normalize(item) for item in known}
        added = [item for item in live if normalize(item) not in known_norm]
        removed = [item for item in known if normalize(item) not in live_norm]
        if added or removed:
            print(f"\nWARNING: live Anecdotes options for '{field_name}' differ from config/anecdotes.yaml.")
            if added:
                print(f"  Available in Anecdotes only (usable here): {', '.join(added)}")
            if removed:
                print(f"  In config only, NOT offered by Anecdotes: {', '.join(removed)}")
            print("  Live Anecdotes metadata is being used.")


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #


def resolve_option(raw: str, options: list[str]) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.isdigit():
        index = int(raw)
        return options[index - 1] if 1 <= index <= len(options) else None
    key = normalize(raw)
    for option in options:
        if normalize(option) == key:
            return option
    return None


def prompt_required(label: str, current: str | None = None) -> str:
    editing = current is not None
    while True:
        print(f"\n{label}")
        if editing:
            print(f"  Current: {current if current else '(empty)'}")
            raw = input("  New value (Enter to keep unchanged): ").strip()
            if not raw:
                if current:
                    return current
                print("  This field is required and is currently empty. Please enter a value.")
                continue
            return raw
        raw = input("  Value: ").strip()
        if raw:
            return raw
        print("  This field is required. Please enter a value.")


def _print_menu(label: str, options: list[str], current: list[str]) -> None:
    print(f"\n{label}")
    current_norm = {normalize(item) for item in current}
    for index, option in enumerate(options, 1):
        marker = "   <- current" if normalize(option) in current_norm else ""
        print(f"  {index}. {option}{marker}")


def select_one(label: str, options: list[str], current: str | None = None) -> str:
    editing = current is not None
    while True:
        _print_menu(label, options, [current] if current else [])
        if editing:
            print(f"  Current: {current if current else '(none)'}")
            raw = input("  Select one (number or name, Enter to keep unchanged): ").strip()
            if not raw and current:
                return current
        else:
            raw = input("  Select one (number or name): ").strip()
        if not raw:
            print("  A selection is required.")
            continue
        match = resolve_option(raw, options)
        if match is not None:
            return match
        print(f"  {raw!r} is not a valid option. Pick a number 1-{len(options)} or type the name.")


def select_many(label: str, options: list[str], current: list[str] | None = None) -> list[str]:
    editing = current is not None
    while True:
        _print_menu(label, options, current or [])
        if editing:
            print(f"  Current: {', '.join(current) if current else '(none)'}")
            raw = input("  Select one or more (comma-separated, Enter to keep unchanged): ").strip()
            if not raw and current:
                return list(current)
        else:
            raw = input("  Select one or more (comma-separated): ").strip()
        if not raw:
            print("  At least one selection is required.")
            continue
        picks: list[str] = []
        invalid: list[str] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            match = resolve_option(token, options)
            if match is None:
                invalid.append(token)
            elif match not in picks:
                picks.append(match)
        if invalid:
            print(f"  Not valid: {', '.join(repr(item) for item in invalid)}")
            continue
        if not picks:
            print("  At least one selection is required.")
            continue
        return picks


def confirm(question: str) -> bool:
    """Explicit opt-in only. Default, and anything unrecognised, is No."""
    answer = input(f"\n{question} [y/N]: ").strip().casefold()
    return answer in {"y", "yes"}


# --------------------------------------------------------------------------- #
# Risk payload reading
# --------------------------------------------------------------------------- #


def top_str(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def internal_id_of(risk: dict[str, Any]) -> str | None:
    found = [risk.get(key) for key in INTERNAL_ID_KEYS]
    strings = [item for item in found if isinstance(item, str) and item]
    for item in strings:
        if item.startswith("risk_"):
            return item
    return strings[0] if strings else None


def display_id_of(risk: dict[str, Any]) -> str | None:
    return top_str(risk, DISPLAY_ID_KEYS)


def name_of(risk: dict[str, Any]) -> str:
    return top_str(risk, NAME_KEYS) or "(unnamed)"


def in_register(risk: dict[str, Any], register_id: str | None) -> bool:
    if not register_id:
        return True
    value = top_str(risk, ("register_id", "registerId"))
    return value is None or value == register_id


def risk_field_values(risk: dict[str, Any]) -> dict[str, Any]:
    raw: Any = None
    for key in ("fields", "custom_fields", "customFields"):
        candidate = risk.get(key)
        if isinstance(candidate, (dict, list)):
            raw = candidate
            break
    if isinstance(raw, dict):
        return dict(raw)
    values: dict[str, Any] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            field_id = item.get("id") or item.get("field_id") or item.get("fieldId")
            if isinstance(field_id, str):
                values[field_id] = item.get("value", item.get("values"))
    return values


def read_current_values(
    risk: dict[str, Any], resolver: FieldResolver, cfg: dict[str, Any]
) -> dict[str, Any]:
    field_names = cfg["field_names"]
    raw_fields = risk_field_values(risk)
    values: dict[str, Any] = {"risk_name": top_str(risk, NAME_KEYS) or ""}
    for key in CUSTOM_FIELD_KEYS:
        field_name = field_names[key]
        values[key] = resolver.decode(field_name, raw_fields.get(resolver.field_id(field_name)))
    return values


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(value) if value else "(none)"
    return str(value) if value else "(empty)"


def ordered_labels(cfg: dict[str, Any]) -> list[tuple[str, str]]:
    field_names = cfg["field_names"]
    return [("risk_name", "Risk name")] + [(key, field_names[key]) for key in CUSTOM_FIELD_KEYS]


def print_summary(title: str, values: dict[str, Any], cfg: dict[str, Any]) -> None:
    print(f"\n{title}")
    print(RULE)
    for key, label in ordered_labels(cfg):
        print(f"\n{label}:")
        print(f"{render(values[key])}")
    print(f"\n{RULE}")


def print_resolution(resolver: FieldResolver, cfg: dict[str, Any], values: dict[str, Any]) -> None:
    print("\nResolved Anecdotes metadata")
    print(RULE)
    for key in CUSTOM_FIELD_KEYS:
        field_name = cfg["field_names"][key]
        field_id, encoded = resolver.encode(field_name, values[key])
        print(f"\n{field_name}")
        print(f"  custom-field id: {field_id}")
        if key in SELECT_KEYS:
            print(f"  selected option name(s): {render(values[key])}")
            print(f"  resolved option id(s):   {render(encoded)}")
        else:
            print("  type: free text")
    print(f"\n{RULE}")


def print_diff(changed: list[str], current: dict[str, Any], proposed: dict[str, Any], cfg: dict[str, Any], header: str) -> None:
    labels = dict(ordered_labels(cfg))
    print(f"\n{header}")
    print(RULE)
    for key in changed:
        print(f"\n{labels[key]}")
        print("\nOLD:")
        print(render(current[key]))
        print("\nNEW:")
        print(render(proposed[key]))
    print(f"\n{RULE}")


# --------------------------------------------------------------------------- #
# Diffing
# --------------------------------------------------------------------------- #


def as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)] if value else []


def values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, list) or isinstance(right, list):
        return sorted(normalize(item) for item in as_list(left)) == sorted(
            normalize(item) for item in as_list(right)
        )
    return normalize(str(left)) == normalize(str(right))


def changed_keys(current: dict[str, Any], proposed: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    return [key for key, _ in ordered_labels(cfg) if not values_equal(current[key], proposed[key])]


def build_patch(
    changed: list[str], proposed: dict[str, Any], resolver: FieldResolver, cfg: dict[str, Any]
) -> dict[str, Any]:
    """Partial update: only fields the user actually changed."""
    patch: dict[str, Any] = {}
    if "risk_name" in changed:
        patch["name"] = proposed["risk_name"]
    fields: dict[str, Any] = {}
    for key in changed:
        if key == "risk_name":
            continue
        field_id, encoded = resolver.encode(cfg["field_names"][key], proposed[key])
        fields[field_id] = encoded
    if fields:
        patch["fields"] = fields
    return patch


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def collect_new_values(resolver: FieldResolver, cfg: dict[str, Any]) -> dict[str, Any]:
    field_names = cfg["field_names"]
    return {
        "risk_name": prompt_required("Risk name"),
        "uki_brand": select_many(field_names["uki_brand"], display_options(resolver, field_names["uki_brand"])),
        "risk_event_description": prompt_required(field_names["risk_event_description"]),
        "domain": select_one(field_names["domain"], display_options(resolver, field_names["domain"])),
        "context_background": prompt_required(field_names["context_background"]),
        "impacted_assets": prompt_required(field_names["impacted_assets"]),
    }


def collect_edits(
    current: dict[str, Any], resolver: FieldResolver, cfg: dict[str, Any]
) -> dict[str, Any]:
    field_names = cfg["field_names"]
    brand_field = field_names["uki_brand"]
    domain_field = field_names["domain"]
    current_domain = current["domain"] if isinstance(current["domain"], str) else ""
    return {
        "risk_name": prompt_required("Risk name", current["risk_name"]),
        "uki_brand": select_many(brand_field, display_options(resolver, brand_field), as_list(current["uki_brand"])),
        "risk_event_description": prompt_required(
            field_names["risk_event_description"], str(current["risk_event_description"])
        ),
        "domain": select_one(domain_field, display_options(resolver, domain_field), current_domain),
        "context_background": prompt_required(
            field_names["context_background"], str(current["context_background"])
        ),
        "impacted_assets": prompt_required(field_names["impacted_assets"], str(current["impacted_assets"])),
    }


def cmd_create(args: argparse.Namespace) -> int:
    cfg = load_config()
    check_register(cfg)
    client = build_client(cfg, require_api_key(), read_only=args.dry_run)
    resolver = FieldResolver(client.get_custom_fields())

    if args.dry_run:
        print(DRY_RUN_BANNER)
    print(f"\nTarget register_id: {cfg['register_id']}")
    warn_on_option_drift(resolver, cfg)

    values = collect_new_values(resolver, cfg)
    print_summary("CREATE RISK", values, cfg)

    payload = build_payload(values, cfg, resolver)
    payload["register_id"] = cfg["register_id"]

    if args.dry_run:
        print_resolution(resolver, cfg, values)
        print("\nRequest that WOULD be sent:")
        print("  POST /risk/v1/risk")
        print(json.dumps(payload, indent=2, sort_keys=True))
        print(f"\n{DRY_RUN_FOOTER}")
        return 0

    if not confirm("Create this risk in Anecdotes?"):
        print("Aborted. Nothing was created in Anecdotes.")
        return 0

    result = client.create_risk(payload)
    internal_id = find_first_string(result, ("id", "risk_id", "riskId"))
    customer_risk_id = find_first_string(result, ("customer_risk_id", "customerRiskId"))
    if not internal_id or not internal_id.startswith("risk_"):
        raise AnecdotesError(
            "Risk was submitted but the response did not expose the expected internal risk_... id. "
            "STOP: check Anecdotes before retrying so you do not create a duplicate."
        )
    print("\nRisk successfully created.")
    print(f"\nRisk ID: {customer_risk_id or '(not returned by Anecdotes)'}")
    print(f"Anecdotes internal ID: {internal_id}")
    return 0


def search_and_select(risks: list[dict[str, Any]]) -> dict[str, Any] | None:
    while True:
        term = input("\nSearch (risk name or Risk ID, Enter to list all): ").strip()
        key = normalize(term)
        matches = [
            risk
            for risk in risks
            if not key
            or key in normalize(name_of(risk))
            or key in normalize(display_id_of(risk) or "")
        ]
        if not matches:
            print(f"\nNo risks matched {term!r}. Nothing has been created or updated.")
            if input("Search again? [y/N]: ").strip().casefold() not in {"y", "yes"}:
                return None
            continue

        print("\nResults:\n")
        for index, risk in enumerate(matches, 1):
            print(f"  {index}. {name_of(risk)}")
            print(f"     Risk ID: {display_id_of(risk) or '(none)'}\n")
        raw = input("Select risk (number): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(matches):
            return matches[int(raw) - 1]
        print("  Invalid selection. An explicit selection is required; nothing was changed.")


def cmd_update(args: argparse.Namespace) -> int:
    cfg = load_config()
    check_register(cfg)
    client = build_client(cfg, require_api_key(), read_only=args.dry_run)
    resolver = FieldResolver(client.get_custom_fields())

    if args.dry_run:
        print(DRY_RUN_BANNER)
    warn_on_option_drift(resolver, cfg)

    register_id = str(cfg.get("register_id") or "")
    risks = [risk for risk in client.list_risks(register_id) if in_register(risk, register_id)]
    if not risks:
        print("Anecdotes returned no risks for this register. Nothing to update.", file=sys.stderr)
        return 1

    selected = search_and_select(risks)
    if selected is None:
        print("No risk selected. Nothing was changed in Anecdotes.")
        return 1

    internal_id = internal_id_of(selected)
    if not internal_id or not internal_id.startswith("risk_"):
        print(
            "ERROR: the selected risk does not expose an internal risk_... id. "
            "Refusing to continue rather than guess the target.",
            file=sys.stderr,
        )
        return 1

    live_risk = client.get_risk(internal_id)
    current = read_current_values(live_risk, resolver, cfg)
    display_id = display_id_of(live_risk) or display_id_of(selected) or "(none)"

    print(f"\nCURRENT VALUES (from Anecdotes)\n{RULE}")
    print(f"\nRisk ID: {display_id}")
    print(f"Anecdotes internal ID: {internal_id}")
    print_summary("Fields", current, cfg)

    proposed = collect_edits(current, resolver, cfg)
    changed = changed_keys(current, proposed, cfg)
    if not changed:
        print("\nNo changes detected. Nothing to update.")
        return 0

    print_diff(changed, current, proposed, cfg, f"UPDATE RISK {display_id}")
    patch = build_patch(changed, proposed, resolver, cfg)

    if args.dry_run:
        print(f"\nRisk ID: {display_id}")
        print(f"Anecdotes internal ID: {internal_id}")
        print(f"Changed fields: {', '.join(changed)}")
        print_resolution(resolver, cfg, proposed)
        print("\nRequest that WOULD be sent:")
        print(f"  PATCH /risk/v1/risk/{internal_id}")
        print(json.dumps(patch, indent=2, sort_keys=True))
        print(f"\n{DRY_RUN_FOOTER}")
        return 0

    if not confirm("Apply these changes to Anecdotes?"):
        print("Aborted. Nothing was changed in Anecdotes.")
        return 0

    client.update_risk(internal_id, patch)
    print("\nRisk successfully updated.")
    print(f"\nRisk ID: {display_id}")
    print(f"Anecdotes internal ID: {internal_id}")
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="risk_cli",
        description=(
            "Interactive CLI for creating and updating risks directly in Anecdotes. "
            "Anecdotes is the source of truth; nothing is written to this repository."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("create", "Interactively create a new risk in Anecdotes."),
        ("update", "Search Anecdotes for an existing risk and update it."),
    ):
        sub = subcommands.add_parser(name, help=help_text)
        sub.add_argument(
            "--dry-run",
            action="store_true",
            help="Read from Anecdotes but block every POST/PATCH/PUT/DELETE.",
        )
    args = parser.parse_args(argv)

    try:
        return cmd_create(args) if args.command == "create" else cmd_update(args)
    except CliError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ReadOnlyModeError as exc:
        print(f"DRY RUN SAFETY: {exc}", file=sys.stderr)
        return 2
    except AnecdotesError as exc:
        print(f"ANECDOTES API ERROR: {exc}", file=sys.stderr)
        hint = STATUS_HINTS.get(getattr(exc, "status_code", None) or 0)
        if hint:
            print(f"HINT: {hint}", file=sys.stderr)
        print("Nothing was changed in Anecdotes by this run.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. Nothing was changed in Anecdotes.")
        return 130
    except EOFError:
        print("\nInput ended unexpectedly. Nothing was changed in Anecdotes.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
