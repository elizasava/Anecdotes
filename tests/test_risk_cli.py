import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import risk_cli
from anecdotes_client import AnecdotesClient, AnecdotesError, FieldResolver, ReadOnlyModeError

SECRET = "SUPER-SECRET-ANECDOTES-TOKEN"

FIELDS = [
    {
        "id": "f-brand",
        "name": "UKI Brand",
        "type": "MultiSelect",
        "options": [
            {"id": "o-skybet", "label": "Sky Bet"},
            {"id": "o-tombola", "label": "tombola"},
            {"id": "o-pokerstars", "label": "Pokerstars"},
        ],
    },
    {"id": "f-desc", "name": "Risk event description", "type": "FreeText"},
    {
        "id": "f-domain",
        "name": "Domain",
        "type": "SingleSelect",
        "options": [
            {"id": "o-phishing", "label": "CYB03 - Phishing"},
            {"id": "o-cloud", "label": "TR04 - Cloud Platform Adoption"},
        ],
    },
    {"id": "f-context", "name": "Context/background", "type": "FreeText"},
    {"id": "f-assets", "name": "Impacted asset/s", "type": "FreeText"},
]

RISK_SUMMARIES = [
    {"id": "risk_aaa", "name": "Supplier outage", "customer_risk_id": "UKI-1234"},
    {"id": "risk_bbb", "name": "Critical supplier failure", "customer_risk_id": "UKI-1392"},
]

RISK_DETAIL = {
    "risk_aaa": {
        "id": "risk_aaa",
        "name": "Supplier outage",
        "customer_risk_id": "UKI-1234",
        "fields": {
            "f-brand": ["o-skybet"],
            "f-desc": "Supplier outage could affect payments.",
            "f-domain": "o-cloud",
            "f-context": "Existing context.",
            "f-assets": "Payments platform",
        },
    },
    "risk_bbb": {
        "id": "risk_bbb",
        "name": "Critical supplier failure",
        "customer_risk_id": "UKI-1392",
        "fields": {
            "f-brand": ["o-tombola"],
            "f-desc": "Supplier failure.",
            "f-domain": "o-phishing",
            "f-context": "Other context.",
            "f-assets": "Wallet",
        },
    },
}


class FakeClient:
    """Stands in for AnecdotesClient; writes are recorded, never sent."""

    def __init__(self, risks=None):
        self.calls = []

    def get_custom_fields(self):
        self.calls.append(("GET", "custom-fields"))
        return FIELDS

    def list_risks(self, register_id=None):
        self.calls.append(("GET", "list_risks", register_id))
        return list(RISK_SUMMARIES)

    def get_risk(self, internal_id):
        self.calls.append(("GET", "get_risk", internal_id))
        if internal_id not in RISK_DETAIL:
            raise AnecdotesError("not found", status_code=404)
        return RISK_DETAIL[internal_id]

    def create_risk(self, payload):
        self.calls.append(("POST", payload))
        return {"id": "risk_new123", "customer_risk_id": "UKI-9999"}

    def update_risk(self, internal_id, payload):
        self.calls.append(("PATCH", internal_id, payload))
        return {}

    def writes(self):
        return [call for call in self.calls if call[0] in {"POST", "PATCH", "PUT", "DELETE"}]


@pytest.fixture
def cli(monkeypatch):
    client = FakeClient()
    monkeypatch.setenv("ANECDOTES", SECRET)
    monkeypatch.setattr(risk_cli, "build_client", lambda cfg, api_key, read_only: client)
    return client


def scripted(monkeypatch, answers):
    answers = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))


CREATE_ANSWERS = [
    "Supplier outage",          # Risk name
    "  sky bet , POKERSTARS ",  # UKI Brand (multi-select, messy casing/spacing)
    "Payments could fail.",     # Risk event description
    "phishing",                 # Domain (lowercase, no CYB code)
    "Some context.",            # Context/background
    "Payments platform",        # Impacted asset/s
]


# --------------------------------------------------------------------------- #
# Transport-level dry-run enforcement
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"items": []}
        self.text = json.dumps(self._payload)
        self.content = self.text.encode()

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._payload


class RecordingSession:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url))
        return FakeResponse()


def make_client(monkeypatch, read_only):
    monkeypatch.setattr(AnecdotesClient, "_exchange_token", lambda self: "fake-jwt")
    client = AnecdotesClient(
        api_key="key",
        api_base_url="https://example.invalid",
        auth_exchange_url="https://auth.invalid",
        user_agent="test",
        read_only=read_only,
    )
    client.session = RecordingSession()
    return client


@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
def test_dry_run_client_blocks_every_write_method(monkeypatch, method):
    client = make_client(monkeypatch, read_only=True)
    with pytest.raises(ReadOnlyModeError):
        client._request(method, "/risk/v1/risk", json={"name": "x"})
    assert client.session.requests == [], "a write escaped to the network in dry-run mode"


def test_dry_run_client_still_allows_reads(monkeypatch):
    client = make_client(monkeypatch, read_only=True)
    client._request("GET", "/custom-fields/v1/fields")
    assert client.session.requests == [("GET", "https://example.invalid/custom-fields/v1/fields")]


def test_create_and_update_helpers_are_blocked_in_dry_run(monkeypatch):
    client = make_client(monkeypatch, read_only=True)
    with pytest.raises(ReadOnlyModeError):
        client.create_risk({"name": "x"})
    with pytest.raises(ReadOnlyModeError):
        client.update_risk("risk_aaa", {"name": "x"})
    assert client.session.requests == []


def test_default_client_is_not_read_only(monkeypatch):
    """The existing GitHub/YAML sync must keep its write ability."""
    client = make_client(monkeypatch, read_only=False)
    client._request("POST", "/risk/v1/risk", json={"name": "x"})
    assert client.session.requests == [("POST", "https://example.invalid/risk/v1/risk")]


def test_client_has_no_delete_capability():
    assert not hasattr(AnecdotesClient, "delete_risk")
    source = Path(risk_cli.__file__).read_text(encoding="utf-8")
    assert "delete_risk" not in source
    assert '("DELETE"' not in source and "'DELETE'" not in source


# --------------------------------------------------------------------------- #
# Option matching
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw", ["Sky Bet", "sky bet", "SKY BET", "  Sky   Bet  ", "1"])
def test_uki_brand_matching_is_case_and_whitespace_insensitive(raw):
    assert risk_cli.resolve_option(raw, ["Sky Bet", "tombola"]) == "Sky Bet"


@pytest.mark.parametrize("raw", ["Phishing", "  phishing ", "PHISHING"])
def test_domain_matching_is_case_and_whitespace_insensitive(raw):
    resolver = FieldResolver(FIELDS)
    options = risk_cli.display_options(resolver, "Domain")
    assert risk_cli.resolve_option(raw, options) == "Phishing"


def test_domain_menu_hides_code_prefixes():
    resolver = FieldResolver(FIELDS)
    assert risk_cli.display_options(resolver, "Domain") == ["Phishing", "Cloud Platform Adoption"]


def test_invalid_option_is_rejected():
    assert risk_cli.resolve_option("Not A Brand", ["Sky Bet"]) is None
    assert risk_cli.resolve_option("99", ["Sky Bet"]) is None


def test_multiselect_accepts_several_values_and_rejects_bad_ones(monkeypatch, capsys):
    scripted(monkeypatch, ["sky bet, nonsense", "sky bet , POKERSTARS"])
    picks = risk_cli.select_many("UKI Brand", ["Sky Bet", "tombola", "Pokerstars"])
    assert picks == ["Sky Bet", "Pokerstars"]
    assert "Not valid" in capsys.readouterr().out


def test_multiselect_resolves_to_option_ids():
    resolver = FieldResolver(FIELDS)
    assert resolver.encode("UKI Brand", ["sky bet", "POKERSTARS"]) == (
        "f-brand",
        ["o-skybet", "o-pokerstars"],
    )


def test_decode_turns_option_ids_back_into_labels():
    resolver = FieldResolver(FIELDS)
    assert resolver.decode("UKI Brand", ["o-skybet", "o-tombola"]) == ["Sky Bet", "tombola"]
    assert resolver.decode("Domain", "o-phishing") == "CYB03 - Phishing"


# --------------------------------------------------------------------------- #
# Confirmation defaults
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "answer,expected",
    [("", False), ("n", False), ("no", False), ("maybe", False), ("Y", True), ("yes", True)],
)
def test_confirm_defaults_to_no(monkeypatch, answer, expected):
    scripted(monkeypatch, [answer])
    assert risk_cli.confirm("Do it?") is expected


def test_create_confirmation_defaults_to_no(monkeypatch, cli, capsys):
    scripted(monkeypatch, CREATE_ANSWERS + [""])
    assert risk_cli.main(["create"]) == 0
    assert cli.writes() == []
    assert "Aborted" in capsys.readouterr().out


def test_update_confirmation_defaults_to_no(monkeypatch, cli, capsys):
    scripted(monkeypatch, ["supplier", "1", "", "", "New description.", "", "", "", ""])
    assert risk_cli.main(["update"]) == 0
    assert cli.writes() == []
    assert "Aborted" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #


def test_create_dry_run_never_posts(monkeypatch, cli, capsys):
    scripted(monkeypatch, CREATE_ANSWERS)
    assert risk_cli.main(["create", "--dry-run"]) == 0
    assert cli.writes() == []
    out = capsys.readouterr().out
    assert risk_cli.DRY_RUN_BANNER in out
    assert risk_cli.DRY_RUN_FOOTER in out
    assert "POST /risk/v1/risk" in out
    assert "o-skybet" in out and "f-brand" in out


def test_create_sends_expected_payload_after_explicit_yes(monkeypatch, cli):
    scripted(monkeypatch, CREATE_ANSWERS + ["y"])
    assert risk_cli.main(["create"]) == 0
    writes = cli.writes()
    assert len(writes) == 1
    method, payload = writes[0]
    assert method == "POST"
    assert payload["name"] == "Supplier outage"
    assert payload["fields"]["f-brand"] == ["o-skybet", "o-pokerstars"]
    assert payload["fields"]["f-domain"] == "o-phishing"
    assert payload["register_id"]


def test_create_does_not_invent_a_risk_id(monkeypatch, cli, capsys):
    scripted(monkeypatch, CREATE_ANSWERS + ["y"])
    risk_cli.main(["create"])
    _, payload = cli.writes()[0]
    assert "risk_key" not in payload and "id" not in payload
    assert "risk_new123" in capsys.readouterr().out


def test_create_rejects_empty_required_text(monkeypatch):
    scripted(monkeypatch, ["", "   ", "Finally a name"])
    assert risk_cli.prompt_required("Risk name") == "Finally a name"


# --------------------------------------------------------------------------- #
# Update
# --------------------------------------------------------------------------- #


def test_update_reads_risks_and_uses_internal_id(monkeypatch, cli):
    scripted(
        monkeypatch,
        ["supplier", "1", "", "sky bet, pokerstars", "Payments and withdrawals.", "", "", "", "y"],
    )
    assert risk_cli.main(["update"]) == 0
    assert ("GET", "list_risks", risk_cli.load_config()["register_id"]) in cli.calls
    assert ("GET", "get_risk", "risk_aaa") in cli.calls
    writes = cli.writes()
    assert len(writes) == 1
    assert writes[0][0] == "PATCH"
    assert writes[0][1] == "risk_aaa"


def test_update_payload_contains_only_changed_fields(monkeypatch, cli):
    scripted(
        monkeypatch,
        ["supplier", "1", "", "sky bet, pokerstars", "Payments and withdrawals.", "", "", "", "y"],
    )
    risk_cli.main(["update"])
    _, _, payload = cli.writes()[0]
    assert "name" not in payload, "unchanged risk name must not be patched"
    assert set(payload["fields"]) == {"f-brand", "f-desc"}
    assert payload["fields"]["f-brand"] == ["o-skybet", "o-pokerstars"]


def test_update_does_nothing_when_no_changes(monkeypatch, cli, capsys):
    scripted(monkeypatch, ["supplier", "1", "", "", "", "", "", ""])
    assert risk_cli.main(["update"]) == 0
    assert cli.writes() == []
    assert "No changes detected. Nothing to update." in capsys.readouterr().out


def test_update_dry_run_never_patches(monkeypatch, cli, capsys):
    scripted(monkeypatch, ["supplier", "1", "", "", "Payments and withdrawals.", "", "", ""])
    assert risk_cli.main(["update", "--dry-run"]) == 0
    assert cli.writes() == []
    out = capsys.readouterr().out
    assert risk_cli.DRY_RUN_BANNER in out
    assert risk_cli.DRY_RUN_FOOTER in out
    assert "PATCH /risk/v1/risk/risk_aaa" in out
    assert "OLD:" in out and "NEW:" in out


def test_ambiguous_search_requires_explicit_selection(monkeypatch, cli, capsys):
    scripted(
        monkeypatch,
        ["supplier", "2", "", "", "Changed description.", "", "", "", "y"],
    )
    risk_cli.main(["update"])
    out = capsys.readouterr().out
    assert "UKI-1234" in out and "UKI-1392" in out
    assert ("GET", "get_risk", "risk_bbb") in cli.calls
    assert cli.writes()[0][1] == "risk_bbb"


def test_rejected_selection_number_does_not_pick_a_risk(monkeypatch, cli, capsys):
    scripted(monkeypatch, ["supplier", "99", "zzz-no-such-risk", "n"])
    assert risk_cli.main(["update"]) == 1
    assert cli.writes() == []
    assert not any(call[1] == "get_risk" for call in cli.calls if len(call) > 1)
    assert "An explicit selection is required" in capsys.readouterr().out


def test_empty_search_results_never_create_or_patch(monkeypatch, cli, capsys):
    scripted(monkeypatch, ["nothing-matches-this", "n"])
    assert risk_cli.main(["update"]) == 1
    assert cli.writes() == []
    out = capsys.readouterr().out
    assert "No risks matched" in out
    assert "Nothing has been created or updated." in out


def test_update_shows_current_values_from_anecdotes(monkeypatch, cli, capsys):
    scripted(monkeypatch, ["supplier", "1", "", "", "", "", "", ""])
    risk_cli.main(["update"])
    out = capsys.readouterr().out
    assert "Supplier outage could affect payments." in out
    assert "Cloud Platform Adoption" in out
    assert "Sky Bet" in out


def test_update_refuses_risk_without_internal_risk_id(monkeypatch, cli, capsys):
    monkeypatch.setattr(cli, "list_risks", lambda register_id=None: [{"id": "abc", "name": "No prefix"}])
    scripted(monkeypatch, ["", "1"])
    assert risk_cli.main(["update"]) == 1
    assert cli.writes() == []
    assert "Refusing to continue" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #


def test_missing_credential_fails_closed(monkeypatch, capsys):
    monkeypatch.delenv("ANECDOTES", raising=False)
    assert risk_cli.main(["create"]) == 2
    assert "ANECDOTES is not set" in capsys.readouterr().err


def test_api_errors_are_reported_without_changing_anything(monkeypatch, cli, capsys):
    monkeypatch.setattr(
        cli, "list_risks", lambda register_id=None: (_ for _ in ()).throw(AnecdotesError("denied", status_code=403))
    )
    assert risk_cli.main(["update"]) == 1
    err = capsys.readouterr().err
    assert "ANECDOTES API ERROR" in err
    assert "lacks permission" in err
    assert "Nothing was changed in Anecdotes" in err


def test_credentials_are_never_printed(monkeypatch, cli, capsys):
    scripted(monkeypatch, CREATE_ANSWERS)
    risk_cli.main(["create", "--dry-run"])
    captured = capsys.readouterr()
    blob = captured.out + captured.err
    assert SECRET not in blob
    assert "Authorization" not in blob
    assert "Bearer" not in blob


def _tracked_files():
    state = {}
    for path in ROOT.rglob("*"):
        if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
            continue
        if path.is_file():
            state[str(path)] = path.stat().st_mtime_ns
    return state


@pytest.mark.parametrize(
    "argv,answers",
    [
        (["create", "--dry-run"], CREATE_ANSWERS),
        (["update", "--dry-run"], ["supplier", "1", "", "", "Changed.", "", "", ""]),
    ],
)
def test_cli_never_writes_repository_files(monkeypatch, cli, argv, answers):
    before = _tracked_files()
    scripted(monkeypatch, answers)
    risk_cli.main(argv)
    assert _tracked_files() == before


def test_cli_does_not_touch_the_mapping_module():
    source = Path(risk_cli.__file__).read_text(encoding="utf-8")
    assert "set_mapping" not in source
    assert "get_mapping" not in source
    assert "MAP_PATH" not in source
    assert "save_yaml" not in source
