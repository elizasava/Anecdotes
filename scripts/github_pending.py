from __future__ import annotations

import base64
import os
import re
from typing import Any

import requests
import yaml

MARKER_RE = re.compile(r"<!--\s*anecdotes-risk-keys:\s*([^>]+?)\s*-->", re.IGNORECASE)


def _fetch_open_prs(repo: str, token: str) -> list[dict[str, Any]]:
    prs: list[dict[str, Any]] = []
    page = 1
    while True:
        response = requests.get(
            f"https://api.github.com/repos/{repo}/pulls",
            params={"state": "open", "per_page": 100, "page": page},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            break
        page_items = [item for item in payload if isinstance(item, dict)]
        prs.extend(page_items)
        if len(page_items) < 100:
            break
        page += 1
    return prs


def _mapping_keys_from_ref(repo: str, token: str, ref: str) -> set[str]:
    response = requests.get(
        f"https://api.github.com/repos/{repo}/contents/system/anecdotes-risk-map.yaml",
        params={"ref": ref},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    if response.status_code == 404:
        return set()
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return set()
    encoded = payload.get("content")
    if not isinstance(encoded, str) or not encoded.strip():
        return set()
    decoded = base64.b64decode(encoded.encode("ascii")).decode("utf-8", errors="replace")
    data = yaml.safe_load(decoded) or {}
    if not isinstance(data, dict):
        return set()
    risks = data.get("risks")
    if not isinstance(risks, dict):
        return set()
    return {str(key).strip().upper() for key in risks.keys() if str(key).strip()}


def pending_mapping_keys() -> set[str]:
    """Return risk keys already present in an open automation mapping PR.

    This is a duplicate-create guard. If GitHub context/token is unavailable (e.g. local run),
    it returns an empty set rather than making GitHub mandatory.
    """
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not repo or not token:
        return set()
    mapping_branch = os.getenv("MAPPING_BRANCH", "automation/anecdotes-map").strip() or "automation/anecdotes-map"
    main_ref = os.getenv("GITHUB_BASE_REF", "main").strip() or "main"

    main_keys = _mapping_keys_from_ref(repo, token, main_ref)
    branch_keys = _mapping_keys_from_ref(repo, token, mapping_branch)
    keys: set[str] = set(branch_keys - main_keys)

    open_prs = _fetch_open_prs(repo, token)
    for pr in open_prs:
        head = ((pr.get("head") or {}).get("ref") or "") if isinstance(pr.get("head"), dict) else ""
        if not (str(head).startswith("automation/anecdotes-map-") or str(head) == mapping_branch):
            continue
        body = pr.get("body") or ""
        for match in MARKER_RE.findall(str(body)):
            for key in match.split(","):
                if key.strip():
                    keys.add(key.strip().upper())
    return keys
