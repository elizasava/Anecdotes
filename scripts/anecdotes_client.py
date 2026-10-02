from __future__ import annotations

import time
from typing import Any

import requests

from common import normalize


class AnecdotesError(RuntimeError):
    pass


class AnecdotesClient:
    def __init__(self, api_key: str, api_base_url: str, auth_exchange_url: str, user_agent: str):
        if not api_key.strip():
            raise ValueError("ANECDOTES secret is empty")
        self.api_key = api_key.strip()
        self.api_base_url = api_base_url.rstrip("/")
        self.auth_exchange_url = auth_exchange_url
        self.user_agent = user_agent
        self.session = requests.Session()
        self.jwt = self._exchange_token()

    def _exchange_token(self) -> str:
        response = requests.get(
            self.auth_exchange_url,
            headers={"x-anecdotes-api-key": self.api_key, "User-Agent": self.user_agent},
            timeout=30,
        )
        if not response.ok:
            raise AnecdotesError(f"JWT exchange failed: HTTP {response.status_code}: {response.text[:500]}")
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

    def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> Any:
        url = f"{self.api_base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.jwt}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(1, 5):
            try:
                response = self.session.request(method, url, headers=headers, json=json, timeout=30)
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 4:
                    break
                time.sleep(2 ** (attempt - 1))
                continue

            if response.status_code == 401 and attempt == 1:
                self.jwt = self._exchange_token()
                headers["Authorization"] = f"Bearer {self.jwt}"
                continue
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt < 4:
                    time.sleep(2 ** (attempt - 1))
                    continue
            if not response.ok:
                raise AnecdotesError(f"{method} {path} failed: HTTP {response.status_code}: {response.text[:1000]}")
            if not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text
        raise AnecdotesError(f"{method} {path} failed after retries: {last_error}")

    def get_custom_fields(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/custom-fields/v1/fields")
        return self._extract_list(payload)

    def create_risk(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request("POST", "/risk/v1/risk", json=payload)
        if not isinstance(result, dict):
            raise AnecdotesError("Create Risk returned an unexpected response")
        return result

    def update_risk(self, internal_id: str, payload: dict[str, Any]) -> Any:
        return self._request("PATCH", f"/risk/v1/risk/{internal_id}", json=payload)

    @staticmethod
    def _extract_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for key in ("items", "data", "fields", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, dict)]
            for value in payload.values():
                if isinstance(value, list) and all(isinstance(x, dict) for x in value):
                    return value
        raise AnecdotesError("Could not find a custom-field list in the Anecdotes response")


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
            available = ", ".join(sorted(f.get("name", "?") for f in self.definitions if isinstance(f.get("name"), str)))
            raise AnecdotesError(f"Custom field {name!r} not found. Available names include: {available[:1000]}")
        return self.by_name[key]

    def encode(self, field_name: str, value: str | list[str]) -> tuple[str, str | list[str]]:
        field = self.field(field_name)
        field_id = field.get("id")
        if not isinstance(field_id, str) or not field_id:
            raise AnecdotesError(f"Custom field {field_name!r} has no id")
        field_type = normalize(str(field.get("type", "")))

        if "text" in field_type or field_type in {"string", "freetext", "free text"}:
            if not isinstance(value, str):
                raise AnecdotesError(f"{field_name} is text but YAML supplied multiple values")
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
                    raise AnecdotesError(f"Value {item!r} not found in Anecdotes field {field_name!r}. Available: {allowed}")
                resolved.append(labels_to_ids[key][0])

            is_multi = "multi" in field_type or isinstance(value, list)
            if is_multi:
                return field_id, resolved
            if len(resolved) != 1:
                raise AnecdotesError(f"{field_name} only supports one value")
            return field_id, resolved[0]

        # Unknown/non-select custom field: preserve string only, fail for arrays.
        if isinstance(value, list):
            raise AnecdotesError(f"Cannot resolve options for multi-value field {field_name!r}; metadata shape is unsupported")
        return field_id, value

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
        aliases = [label]
        if " - " in label:
            aliases.append(label.split(" - ", 1)[1])
        return list(dict.fromkeys(aliases))
