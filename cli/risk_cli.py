#!/usr/bin/env python3
"""Standalone interactive CLI for creating and updating risks in Anecdotes.

Anecdotes is the source of truth. This file is entirely self-contained: it has no
dependency on the GitHub/YAML risk workflow, reads no config file, writes no file,
and never opens a pull request. The only third-party dependency is `requests`.

Usage:
    export ANECDOTES='<api token>'
    python3 risk_cli.py create [--dry-run]
    python3 risk_cli.py update [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any

import requests

try:  # Gives prompts arrow-key line editing instead of raw escape codes.
    import readline  # noqa: F401
except ImportError:
    pass

# --------------------------------------------------------------------------- #
# Configuration (override via environment variables)
# --------------------------------------------------------------------------- #

REGISTER_ID = os.getenv("ANECDOTES_REGISTER_ID", "830f13d3-1f0b-4659-8fb3-8ab5a2bf737b")
API_BASE_URL = os.getenv("ANECDOTES_API_BASE_URL", "https://gateway.anecdotes.ai").rstrip("/")
AUTH_EXCHANGE_URL = os.getenv(
    "ANECDOTES_AUTH_URL", "https://api.anecdotes.ai/identity/v1/apikey/exchange"
)
USER_AGENT = os.getenv("ANECDOTES_USER_AGENT", "anecdotes-risk-cli/1.0")

# Human-facing Anecdotes custom-field names. Ids are always resolved at runtime.
FIELD_NAMES = {
    "uki_brand": "UKI Brand",
    "risk_event_description": "Risk event description",
    "domain": "Domain",
    "context_background": "Context/background",
    "impacted_assets": "Impacted asset/s",
    "cia": "CIA",
    "pii": "Impacted asset contains PII?",
    "tribe": "Tribe",
    "operational_impact": "Operational impact (Tech, Process, People)",
    "reputational_impact": "Reputational impact (UKI)",
    "regulatory_legal_impact": "Regulatory and legal impact (UKI)",
    "financial_impact": "Financial impact (UKI)",
    "target_impact": "Target impact",
    "target_likelihood": "Target likelihood",
}

CUSTOM_FIELD_KEYS = (
    "uki_brand",
    "risk_event_description",
    "domain",
    "context_background",
    "impacted_assets",
    "cia",
    "pii",
    "tribe",
    "operational_impact",
    "reputational_impact",
    "regulatory_legal_impact",
    "financial_impact",
    "target_impact",
    "target_likelihood",
)
SELECT_KEYS = ("uki_brand", "domain")
MULTI_SELECT_KEYS = ("uki_brand", "cia")
TEXT_KEYS = ("risk_event_description", "context_background", "impacted_assets")
RATING_KEYS = (
    "operational_impact",
    "reputational_impact",
    "regulatory_legal_impact",
    "financial_impact",
    "target_impact",
    "target_likelihood",
)

# Expected options, used only to warn when live Anecdotes metadata has drifted.
# Live metadata always wins.
EXPECTED_OPTIONS = {
    "uki_brand": [
        "Sky Bet",
        "tombola",
        "Sky Gaming",
        "Betfair",
        "Paddy Power",
        "Pokerstars",
    ],
    "domain": [
        "Malware Event (Ransomware/Spyware)",
        "Supply Chain",
        "Phishing",
        "Cloud Platform Adoption",
        "Tech Regulatory & Compliance",
        "Manage Tech Availability",
        "IT Operational Resilience",
        "Misconfiguration",
        "Data Exfiltration",
        "System Resilience (inc. DDoS)",
        "End User Tech Risk (Shadow IT)",
        "Third Party & Outsourcing Risk",
        "Emerging Tech Risk (AI, Quantum)",
        "AI Cyber Risk",
        "Legacy Systems & Tech Debt",
        "Access Management Risk",
        "Insider Threat",
        "Data Governance & Quality",
        "Manage Tech Change",
        "Cyber Governance",
    ],
}

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


def normalize(value: str) -> str:
    """Case-insensitive, whitespace-tolerant comparison key."""
    return re.sub(r"\s+", " ", str(value).strip().casefold())


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class AnecdotesError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ReadOnlyModeError(AnecdotesError):
    """Raised when a mutating request is attempted while the client is read-only."""


class CliError(RuntimeError):
    """User-facing configuration or input problem; never contains credentials."""


# --------------------------------------------------------------------------- #
# Anecdotes API client
# --------------------------------------------------------------------------- #


class AnecdotesClient:
    READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    MAX_ATTEMPTS = 4

    def __init__(
        self,
        api_key: str,
        api_base_url: str = API_BASE_URL,
        auth_exchange_url: str = AUTH_EXCHANGE_URL,
        user_agent: str = USER_AGENT,
        read_only: bool = False,
    ):
        if not api_key.strip():
            raise ValueError("ANECDOTES api key is empty")
        self.api_key = api_key.strip()
        self.api_base_url = api_base_url.rstrip("/")
        self.auth_exchange_url = auth_exchange_url
        self.user_agent = user_agent
        self.read_only = read_only
        self.session = requests.Session()
        self.jwt = self._exchange_token()

    def _exchange_token(self) -> str:
        response = requests.get(
            self.auth_exchange_url,
            headers={"x-anecdotes-api-key": self.api_key, "User-Agent": self.user_agent},
            timeout=30,
        )
        if not response.ok:
            raise AnecdotesError(
                f"JWT exchange failed: HTTP {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError:
            payload = response.text.strip().strip('"')
        token = self._find_token(payload)
        if not token:
            raise AnecdotesError("JWT exchange succeeded but no token could be found in the response")
        return token

    @classmethod
    def _find_token(cls, payload: Any) -> str | None:
        if isinstance(payload, str) and payload:
            return payload
        if isinstance(payload, dict):
            for key in ("token", "jwt", "access_token", "id_token"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
            for value in payload.values():
                token = cls._find_token(value)
                if token:
                    return token
        return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        # Single choke point: in read-only mode nothing but safe reads can leave the process.
        if self.read_only and method.upper() not in self.READ_METHODS:
            raise ReadOnlyModeError(
                f"Blocked {method.upper()} {path}: Anecdotes client is in read-only (dry-run) mode"
            )
        url = f"{self.api_base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.jwt}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                response = self.session.request(
                    method, url, headers=headers, json=json, params=params, timeout=30
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.MAX_ATTEMPTS:
                    break
                time.sleep(2 ** (attempt - 1))
                continue

            if response.status_code == 401 and attempt == 1:
                self.jwt = self._exchange_token()
                headers["Authorization"] = f"Bearer {self.jwt}"
                continue
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt < self.MAX_ATTEMPTS:
                    time.sleep(2 ** (attempt - 1))
                    continue
            if not response.ok:
                raise AnecdotesError(
                    f"{method} {path} failed: HTTP {response.status_code}: {response.text[:1000]}",
                    status_code=response.status_code,
                )
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text
        raise AnecdotesError(f"{method} {path} failed after retries: {last_error}")

    def get_custom_fields(self) -> list[dict[str, Any]]:
        return self._extract_list(self._request("GET", "/custom-fields/v1/fields"))

    def list_risks(self, register_id: str | None = None) -> list[dict[str, Any]]:
        attempts: list[tuple[str, dict[str, Any] | None]] = []
        for path in ("/risk/v1/risk", "/risk/v1/risks"):
            if register_id:
                attempts.append((path, {"register_id": register_id}))
            attempts.append((path, None))

        problems: list[str] = []
        for path, params in attempts:
            try:
                return self._extract_list(self._request("GET", path, params=params), label="risk")
            except ReadOnlyModeError:
                raise
            except AnecdotesError as exc:
                problems.append(f"GET {path} ({params or 'no params'}) -> {exc}")
        raise AnecdotesError("Could not list risks from Anecdotes. Tried:\n  " + "\n  ".join(problems))

    def get_risk(self, internal_id: str) -> dict[str, Any]:
        result = self._request("GET", f"/risk/v1/risk/{internal_id}")
        if isinstance(result, dict):
            for key in ("risk", "data", "item", "result"):
                nested = result.get(key)
                if isinstance(nested, dict) and nested:
                    return nested
            return result
        raise AnecdotesError(f"Get Risk {internal_id} returned an unexpected response")

    def create_risk(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request("POST", "/risk/v1/risk", json=payload)
        if not isinstance(result, dict):
            raise AnecdotesError("Create Risk returned an unexpected response")
        return result

    def update_risk(self, internal_id: str, payload: dict[str, Any]) -> Any:
        return self._request("PATCH", f"/risk/v1/risk/{internal_id}", json=payload)

    @staticmethod
    def _extract_list(payload: Any, label: str = "custom-field") -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for key in ("items", "data", "fields", "results", "risks"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
            for value in payload.values():
                if isinstance(value, list) and all(isinstance(x, dict) for x in value):
                    return value
        raise AnecdotesError(f"Could not find a {label} list in the Anecdotes response")


# --------------------------------------------------------------------------- #
# Custom-field / option resolution
# --------------------------------------------------------------------------- #


class FieldResolver:
    def __init__(self, definitions: list[dict[str, Any]]):
        self.definitions = definitions
        self.by_name: dict[str, dict[str, Any]] = {}
        for field in definitions:
            name = field.get("name")
            if isinstance(name, str):
                key = normalize(name)
                if key in self.by_name:
                    raise AnecdotesError(f"Duplicate custom-field name after case normalization: {name}")
                self.by_name[key] = field

    def field(self, name: str) -> dict[str, Any]:
        key = normalize(name)
        if key not in self.by_name:
            available = ", ".join(
                sorted(f.get("name", "?") for f in self.definitions if isinstance(f.get("name"), str))
            )
            raise AnecdotesError(f"Custom field {name!r} not found. Available names include: {available[:1000]}")
        return self.by_name[key]

    def field_id(self, name: str) -> str:
        field_id = self.field(name).get("id")
        if not isinstance(field_id, str) or not field_id:
            raise AnecdotesError(f"Custom field {name!r} has no id")
        return field_id

    def is_multi_select(self, name: str) -> bool:
        return "multi" in normalize(str(self.field(name).get("type", "")))

    def option_labels(self, name: str) -> list[str]:
        labels: list[str] = []
        for option in self._options(self.field(name)):
            label = option.get("name") or option.get("label") or option.get("value") or option.get("title")
            if isinstance(label, str) and label not in labels:
                labels.append(label)
        return labels

    def encode(self, field_name: str, value: str | list[str]) -> tuple[str, str | list[str]]:
        field = self.field(field_name)
        field_id = self.field_id(field_name)
        field_type = normalize(str(field.get("type", "")))

        if "text" in field_type or field_type in {"string", "freetext", "free text"}:
            if not isinstance(value, str):
                raise AnecdotesError(f"{field_name} is a text field but several values were supplied")
            return field_id, value

        options = self._options(field)
        if options:
            labels_to_ids: dict[str, tuple[str, str]] = {}
            for option in options:
                option_id = option.get("id") or option.get("valueId") or option.get("uuid")
                label = option.get("name") or option.get("label") or option.get("value") or option.get("title")
                if isinstance(option_id, str) and isinstance(label, str):
                    for alias in self._label_aliases(label):
                        labels_to_ids[normalize(alias)] = (option_id, label)

            values = value if isinstance(value, list) else [value]
            resolved: list[str] = []
            for item in values:
                key = normalize(item)
                if key not in labels_to_ids:
                    allowed = ", ".join(sorted(label for _, label in labels_to_ids.values()))
                    raise AnecdotesError(
                        f"Value {item!r} not found in Anecdotes field {field_name!r}. Available: {allowed}"
                    )
                resolved.append(labels_to_ids[key][0])

            if "multi" in field_type or isinstance(value, list):
                return field_id, resolved
            if len(resolved) != 1:
                raise AnecdotesError(f"{field_name} only supports one value")
            return field_id, resolved[0]

        if isinstance(value, list):
            raise AnecdotesError(
                f"Cannot resolve options for multi-value field {field_name!r}; metadata shape is unsupported"
            )
        return field_id, value

    def decode(self, field_name: str, raw: Any) -> str | list[str]:
        """Inverse of encode: turn stored option ids back into human-readable labels."""
        options = self._options(self.field(field_name))
        if not options:
            return raw if isinstance(raw, str) else ("" if raw is None else str(raw))

        by_id: dict[str, str] = {}
        for option in options:
            option_id = option.get("id") or option.get("valueId") or option.get("uuid")
            label = option.get("name") or option.get("label") or option.get("value") or option.get("title")
            if isinstance(option_id, str) and isinstance(label, str):
                by_id[option_id] = label

        def one(item: Any) -> str:
            if isinstance(item, dict):
                item = item.get("id") or item.get("valueId") or item.get("value") or ""
            return by_id.get(item, str(item)) if isinstance(item, str) else str(item)

        if isinstance(raw, list):
            return [one(item) for item in raw]
        if raw is None or raw == "":
            return [] if self.is_multi_select(field_name) else ""
        decoded = one(raw)
        return [decoded] if self.is_multi_select(field_name) else decoded

    @classmethod
    def _options(cls, field: dict[str, Any]) -> list[dict[str, Any]]:
        option_keys = {"options", "values", "items", "choices", "enumValues", "selectOptions"}

        def walk(node: Any) -> list[dict[str, Any]]:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in option_keys and isinstance(value, list):
                        if all(isinstance(x, dict) for x in value):
                            return value
                        if all(isinstance(x, str) for x in value):
                            return [{"id": item, "label": item} for item in value]
                    if key in option_keys and isinstance(value, dict):
                        if all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                            return [{"id": option_id, "label": label} for option_id, label in value.items()]
                    found = walk(value)
                    if found:
                        return found
            elif isinstance(node, list):
                for item in node:
                    found = walk(item)
                    if found:
                        return found
            return []

        return walk(field)

    @staticmethod
    def _label_aliases(label: str) -> list[str]:
        """'CYB01 - Phishing' is also addressable as 'Phishing'."""
        aliases = [label]
        if " - " in label:
            aliases.append(label.split(" - ", 1)[1])
            numeric_prefix = re.match(r"^\s*([1-5])\s+-", label)
            if numeric_prefix:
                aliases.append(numeric_prefix.group(1))
        return list(dict.fromkeys(aliases))


def live_field_name(resolver: FieldResolver, key: str) -> str:
    expected = FIELD_NAMES[key]
    available = [
        item["name"]
        for item in resolver.definitions
        if isinstance(item.get("name"), str)
    ]
    exact = [name for name in available if normalize(name) == normalize(expected)]
    if len(exact) == 1:
        return exact[0]
    raise AnecdotesError(
        f"Custom field {expected!r} was not found in live Anecdotes metadata. "
        f"Available names: {', '.join(sorted(available))}"
    )


# --------------------------------------------------------------------------- #
# Setup helpers
# --------------------------------------------------------------------------- #


def require_api_key() -> str:
    api_key = os.getenv("ANECDOTES", "").strip()
    if not api_key:
        raise CliError(
            "Environment variable ANECDOTES is not set. "
            "Export your Anecdotes API token before running this CLI."
        )
    return api_key


def build_client(api_key: str, read_only: bool) -> AnecdotesClient:
    return AnecdotesClient(api_key=api_key, read_only=read_only)


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


def options_for(resolver: FieldResolver, key: str) -> list[str]:
    return display_options(resolver, live_field_name(resolver, key))


def rating_options_for(resolver: FieldResolver, key: str) -> list[str]:
    field_name = live_field_name(resolver, key)
    by_rating: dict[str, str] = {}
    for label in resolver.option_labels(field_name):
        match = re.match(r"^\s*([1-5])(?=\s|$|[-:.)])", label)
        if not match:
            continue
        rating = match.group(1)
        if rating in by_rating:
            raise AnecdotesError(f"Rating {rating} is duplicated in Anecdotes field {field_name!r}")
        by_rating[rating] = rating
    expected = [str(value) for value in range(1, 6)]
    if set(by_rating) != set(expected):
        raise AnecdotesError(
            f"Anecdotes field {field_name!r} must provide ratings 1 through 5. "
            f"Found: {', '.join(sorted(by_rating)) or '(none)'}"
        )
    return expected


def rating_number(value: Any) -> Any:
    if isinstance(value, str):
        match = re.match(r"^\s*([1-5])(?=\s|$|[-:.)])", value)
        if match:
            return match.group(1)
    return value


def display_label_map(resolver: FieldResolver, field_name: str) -> dict[str, str]:
    """Maps each live option label onto the form shown in menus."""
    return {
        normalize(raw): shown
        for raw, shown in zip(resolver.option_labels(field_name), display_options(resolver, field_name))
    }


def to_display(resolver: FieldResolver, field_name: str, value: Any) -> Any:
    """Keeps stored values comparable with menu options, so 'TR3 - X' and 'X' match."""
    by_label = display_label_map(resolver, field_name)
    if isinstance(value, list):
        return [by_label.get(normalize(item), item) for item in value]
    if isinstance(value, str):
        return by_label.get(normalize(value), value)
    return value


def warn_on_option_drift(resolver: FieldResolver) -> None:
    for key in SELECT_KEYS:
        field_name = FIELD_NAMES[key]
        live = display_options(resolver, field_name)
        expected = EXPECTED_OPTIONS[key]
        live_norm = {normalize(item) for item in live}
        expected_norm = {normalize(item) for item in expected}
        added = [item for item in live if normalize(item) not in expected_norm]
        removed = [item for item in expected if normalize(item) not in live_norm]
        if added or removed:
            print(f"\nWARNING: live Anecdotes options for '{field_name}' differ from the expected list.")
            if added:
                print(f"  Available in Anecdotes only (usable here): {', '.join(added)}")
            if removed:
                print(f"  Expected but NOT offered by Anecdotes: {', '.join(removed)}")
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
                return current
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


def select_rating(label: str, options: list[str], current: str | None = None) -> str:
    editing = current is not None
    while True:
        print(f"\n{label}")
        print("  1   2   3   4   5")
        if editing:
            print(f"  Current: {current if current else '(empty)'}")
            raw = input("  Select a value from 1 to 5 (Enter to keep unchanged): ").strip()
            if not raw and current:
                return current
        else:
            raw = input("  Select a value from 1 to 5: ").strip()
        if raw in options:
            return raw
        print("  Enter a number from 1 to 5.")


def select_many(
    label: str,
    options: list[str],
    current: list[str] | None = None,
    default: list[str] | None = None,
) -> list[str]:
    editing = current is not None
    selected = current if editing else default
    while True:
        _print_menu(label, options, selected or [])
        if editing:
            print(f"  Current: {', '.join(current) if current else '(none)'}")
            raw = input("  Select one or more (comma-separated, Enter to keep unchanged): ").strip()
        elif default is not None:
            print(f"  Default: {', '.join(default)}")
            raw = input("  Select one or more (comma-separated, Enter to keep default): ").strip()
        else:
            raw = input("  Select one or more (comma-separated): ").strip()
        if not raw and editing:
            return list(current or [])
        if not raw and default:
            return list(default)
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


def internal_id_of(risk: dict[str, Any]) -> str | None:
    strings = [risk.get(key) for key in INTERNAL_ID_KEYS]
    strings = [item for item in strings if isinstance(item, str) and item]
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


def read_current_values(risk: dict[str, Any], resolver: FieldResolver) -> dict[str, Any]:
    raw_fields = risk_field_values(risk)
    values: dict[str, Any] = {"risk_name": top_str(risk, NAME_KEYS) or ""}
    for key in CUSTOM_FIELD_KEYS:
        field_name = live_field_name(resolver, key)
        value = resolver.decode(field_name, raw_fields.get(resolver.field_id(field_name)))
        if key in RATING_KEYS:
            values[key] = rating_number(value)
        else:
            values[key] = to_display(resolver, field_name, value) if key not in TEXT_KEYS else value
    return values


def build_create_payload(values: dict[str, Any], resolver: FieldResolver) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key in CUSTOM_FIELD_KEYS:
        field_name = live_field_name(resolver, key)
        field_id, encoded_value = resolver.encode(field_name, values[key])
        encoded[field_id] = encoded_value
    return {"name": values["risk_name"], "fields": encoded, "register_id": REGISTER_ID}


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def render(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(value) if value else "(none)"
    return str(value) if value else "(empty)"


def ordered_labels() -> list[tuple[str, str]]:
    return [("risk_name", "Risk name")] + [(key, FIELD_NAMES[key]) for key in CUSTOM_FIELD_KEYS]


def print_summary(title: str, values: dict[str, Any]) -> None:
    print(f"\n{title}")
    print(RULE)
    for key, label in ordered_labels():
        print(f"\n{label}:")
        print(f"{render(values[key])}")
    print(f"\n{RULE}")


def print_resolution(resolver: FieldResolver, values: dict[str, Any]) -> None:
    print("\nResolved Anecdotes metadata")
    print(RULE)
    for key in CUSTOM_FIELD_KEYS:
        field_name = FIELD_NAMES[key]
        actual_name = live_field_name(resolver, key)
        field_id, encoded = resolver.encode(actual_name, values[key])
        print(f"\n{field_name}")
        print(f"  custom-field id: {field_id}")
        if key not in TEXT_KEYS:
            print(f"  selected option name(s): {render(values[key])}")
            print(f"  resolved option id(s):   {render(encoded)}")
        else:
            print("  type: free text")
    print(f"\n{RULE}")


def print_diff(changed: list[str], current: dict[str, Any], proposed: dict[str, Any], header: str) -> None:
    labels = dict(ordered_labels())
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


def changed_keys(current: dict[str, Any], proposed: dict[str, Any]) -> list[str]:
    return [key for key, _ in ordered_labels() if not values_equal(current[key], proposed[key])]


def build_patch(changed: list[str], proposed: dict[str, Any], resolver: FieldResolver) -> dict[str, Any]:
    """Partial update: only fields the user actually changed."""
    patch: dict[str, Any] = {}
    if "risk_name" in changed:
        patch["name"] = proposed["risk_name"]
    fields: dict[str, Any] = {}
    for key in changed:
        if key == "risk_name":
            continue
        field_id, encoded = resolver.encode(live_field_name(resolver, key), proposed[key])
        fields[field_id] = encoded
    if fields:
        patch["fields"] = fields
    return patch


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def collect_new_values(resolver: FieldResolver) -> dict[str, Any]:
    brand_field = live_field_name(resolver, "uki_brand")
    domain_field = live_field_name(resolver, "domain")
    values = {
        "risk_name": prompt_required("Risk name"),
        "uki_brand": select_many(brand_field, display_options(resolver, brand_field)),
        "risk_event_description": prompt_required(FIELD_NAMES["risk_event_description"]),
        "domain": select_one(domain_field, display_options(resolver, domain_field)),
        "context_background": prompt_required(FIELD_NAMES["context_background"]),
        "impacted_assets": prompt_required(FIELD_NAMES["impacted_assets"]),
    }
    cia_name = live_field_name(resolver, "cia")
    cia_options = display_options(resolver, cia_name)
    default_cia = [
        resolve_option(label, cia_options)
        for label in ("Availability", "Confidentiality", "Integrity")
    ]
    if any(value is None for value in default_cia):
        raise AnecdotesError(
            "Live CIA options must include Availability, Confidentiality, and Integrity. "
            f"Found: {', '.join(cia_options)}"
        )
    values["cia"] = select_many("CIA", cia_options, default=[value for value in default_cia if value])

    values["pii"] = select_one(FIELD_NAMES["pii"], options_for(resolver, "pii"))
    for key in RATING_KEYS:
        values[key] = select_rating(FIELD_NAMES[key], rating_options_for(resolver, key))


    tribe_name = live_field_name(resolver, "tribe")
    tribe_options = display_options(resolver, tribe_name)
    gaming = resolve_option("Gaming", tribe_options)
    if gaming is None:
        raise AnecdotesError(f"Live Tribe options do not include Gaming. Found: {', '.join(tribe_options)}")
    values["tribe"] = [gaming] if resolver.is_multi_select(tribe_name) else gaming
    return values


def collect_edits(current: dict[str, Any], resolver: FieldResolver) -> dict[str, Any]:
    brand_field = live_field_name(resolver, "uki_brand")
    domain_field = live_field_name(resolver, "domain")
    current_domain = current["domain"] if isinstance(current["domain"], str) else ""
    proposed = {
        "risk_name": prompt_required("Risk name", current["risk_name"]),
        "uki_brand": select_many(
            brand_field, display_options(resolver, brand_field), as_list(current["uki_brand"])
        ),
        "risk_event_description": prompt_required(
            FIELD_NAMES["risk_event_description"], str(current["risk_event_description"])
        ),
        "domain": select_one(domain_field, display_options(resolver, domain_field), current_domain),
        "context_background": prompt_required(
            FIELD_NAMES["context_background"], str(current["context_background"])
        ),
        "impacted_assets": prompt_required(
            FIELD_NAMES["impacted_assets"], str(current["impacted_assets"])
        ),
    }
    for key in CUSTOM_FIELD_KEYS[5:]:
        field_name = live_field_name(resolver, key)
        options = display_options(resolver, field_name)
        current_value = current[key]
        if key in MULTI_SELECT_KEYS:
            proposed[key] = select_many(
                FIELD_NAMES[key], options, as_list(current_value)
            )
        elif key == "tribe":
            gaming = resolve_option("Gaming", options)
            if gaming is None:
                raise AnecdotesError(f"Live Tribe options do not include Gaming. Found: {', '.join(options)}")
            current_tribe = as_list(current_value)
            proposed[key] = select_one(
                FIELD_NAMES[key], [gaming], current_tribe[0] if len(current_tribe) == 1 else ""
            )
        elif key in RATING_KEYS:
            proposed[key] = select_rating(
                FIELD_NAMES[key], rating_options_for(resolver, key), str(rating_number(current_value))
            )
        else:
            current_scalar = current_value if isinstance(current_value, str) else ""
            proposed[key] = select_one(FIELD_NAMES[key], options, current_scalar)
    return proposed


def cmd_create(args: argparse.Namespace) -> int:
    client = build_client(require_api_key(), read_only=args.dry_run)
    resolver = FieldResolver(client.get_custom_fields())

    if args.dry_run:
        print(DRY_RUN_BANNER)
    print(f"\nTarget register_id: {REGISTER_ID}")
    warn_on_option_drift(resolver)

    values = collect_new_values(resolver)
    print_summary("CREATE RISK", values)
    payload = build_create_payload(values, resolver)

    if args.dry_run:
        print_resolution(resolver, values)
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
    client = build_client(require_api_key(), read_only=args.dry_run)
    resolver = FieldResolver(client.get_custom_fields())

    if args.dry_run:
        print(DRY_RUN_BANNER)
    warn_on_option_drift(resolver)

    risks = [risk for risk in client.list_risks(REGISTER_ID) if in_register(risk, REGISTER_ID)]
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
    current = read_current_values(live_risk, resolver)
    display_id = display_id_of(live_risk) or display_id_of(selected) or "(none)"

    print(f"\nCURRENT VALUES (from Anecdotes)\n{RULE}")
    print(f"\nRisk ID: {display_id}")
    print(f"Anecdotes internal ID: {internal_id}")
    print_summary("Fields", current)

    proposed = collect_edits(current, resolver)
    changed = changed_keys(current, proposed)
    if not changed:
        print("\nNo changes detected. Nothing to update.")
        return 0

    print_diff(changed, current, proposed, f"UPDATE RISK {display_id}")
    patch = build_patch(changed, proposed, resolver)

    if args.dry_run:
        print(f"\nRisk ID: {display_id}")
        print(f"Anecdotes internal ID: {internal_id}")
        print(f"Changed fields: {', '.join(changed)}")
        print_resolution(resolver, proposed)
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
            "Anecdotes is the source of truth; this tool writes no local files."
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
            help="Read from Anecdotes but block every write request.",
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
