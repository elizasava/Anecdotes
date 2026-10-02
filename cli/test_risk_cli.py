import json
import re
import sys
from pathlib import Path

import pytest

CLI_DIR = Path(__file__).resolve().parent
ROOT = CLI_DIR.parent
sys.path.insert(0, str(CLI_DIR))

import risk_cli
from risk_cli import AnecdotesClient, AnecdotesError, FieldResolver, ReadOnlyModeError

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
    {
        "id": "f-cia",
        "name": "CIA",
        "type": "MultiSelect",
        "options": [
            {"id": "o-availability", "label": "Availability"},
            {"id": "o-confidentiality", "label": "Confidentiality"},
            {"id": "o-integrity", "label": "Integrity"},
        ],
    },
    {
        "id": "f-pii",
        "name": "Impacted asset contains PII?",
        "type": "SingleSelect",
        "options": [
            {"id": "o-pii-no", "label": "No"},
            {"id": "o-pii-unknown", "label": "Unknown"},
            {"id": "o-pii-yes", "label": "Yes"},
        ],
    },
    {
        "id": "f-tribe",
        "name": "Tribe",
        "type": "MultiSelect",
        "options": [
            {"id": "o-gaming", "label": "Gaming"},
            {"id": "o-other-tribe", "label": "Other"},
        ],
    },
    {
        "id": "f-operational",
        "name": "Operational impact (Tech, Process, People)",
        "type": "SingleSelect",
        "options": [{"id": f"o-operational-{n}", "label": str(n)} for n in range(1, 6)],
    },
    {
        "id": "f-reputational",
        "name": "Reputational impact (UKI)",
        "type": "SingleSelect",
        "options": [{"id": f"o-reputational-{n}", "label": str(n)} for n in range(1, 6)],
    },
    {
        "id": "f-regulatory",
        "name": "Regulatory and legal impact (UKI)",
        "type": "SingleSelect",
        "options": [{"id": f"o-regulatory-{n}", "label": str(n)} for n in range(1, 6)],
    },
    {
        "id": "f-financial",
        "name": "Financial impact (UKI)",
        "type": "SingleSelect",
        "options": [{"id": f"o-financial-{n}", "label": str(n)} for n in range(1, 6)],
    },
    {
        "id": "f-target-impact",
        "name": "Target impact",
        "type": "SingleSelect",
        "options": [
            {"id": f"o-target-impact-{n}", "label": str(n)} for n in range(5, 0, -1)
        ] + [{"id": "o-target-impact-example", "label": "e.g. 2, 1, 4 (select one)"}],
    },
    {
        "id": "f-target-likelihood",
        "name": "Target likelihood",
        "type": "SingleSelect",
        "options": [{"id": f"o-target-likelihood-{n}", "label": str(n)} for n in range(1, 6)],
    },
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
            "f-cia": ["o-availability", "o-confidentiality", "o-integrity"],
            "f-pii": "o-pii-no",
            "f-tribe": ["o-gaming"],
            "f-operational": "o-operational-1",
            "f-reputational": "o-reputational-1",
            "f-regulatory": "o-regulatory-1",
            "f-financial": "o-financial-1",
            "f-target-impact": "o-target-impact-1",
            "f-target-likelihood": "o-target-likelihood-1",
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
            "f-cia": ["o-availability"],
            "f-pii": "o-pii-unknown",
            "f-tribe": ["o-gaming"],
            "f-operational": "o-operational-2",
            "f-reputational": "o-reputational-2",
            "f-regulatory": "o-regulatory-2",
            "f-financial": "o-financial-2",
            "f-target-impact": "o-target-impact-2",
            "f-target-likelihood": "o-target-likelihood-2",
        },
    },
}


class FakeClient:
    """Stands in for AnecdotesClient; writes are recorded, never sent."""

    def __init__(self):
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
    monkeypatch.setattr(risk_cli, "build_client", lambda api_key, read_only: client)
    return client


def scripted(monkeypatch, answers):
    answers = iter(answers)

    def next_answer(prompt=""):
        return next(answers)

    monkeypatch.setattr("builtins.input", next_answer)


CREATE_ANSWERS = [
    "Supplier outage",          # Risk name
    "  sky bet , POKERSTARS ",  # UKI Brand (multi-select, messy casing/spacing)
    "Payments could fail.",     # Risk event description
    "phishing",                 # Domain (lowercase, no CYB code)
    "Some context.",            # Context/background
    "Payments platform",        # Impacted asset/s
    "",                         # CIA defaults to all three options
    "1",                        # PII: No
    "1",                        # Operational impact
    "1",                        # Reputational impact
    "1",                        # Regulatory and legal impact
    "1",                        # Financial impact
    "1",                        # Target impact
    "1",                        # Target likelihood
]


# --------------------------------------------------------------------------- #
# Standalone guarantees
# --------------------------------------------------------------------------- #


def test_cli_is_a_single_self_contained_file():
    source = Path(risk_cli.__file__).read_text(encoding="utf-8")
    for forbidden in ("from common import", "from sync_risks import", "import yaml", "mapping"):
        assert forbidden not in source, f"CLI must not depend on {forbidden!r}"


def test_cli_imports_no_workflow_modules():
    """Only stdlib plus `requests` may be imported."""
    source = Path(risk_cli.__file__).read_text(encoding="utf-8")
    imports = re.findall(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", source, flags=re.MULTILINE)
    allowed = {"argparse", "json", "os", "re", "sys", "time", "typing", "requests", "readline", "__future__"}
    assert set(imports) <= allowed, f"unexpected imports: {set(imports) - allowed}"


def test_cli_has_no_delete_capability():
    assert not hasattr(AnecdotesClient, "delete_risk")
    source = Path(risk_cli.__file__).read_text(encoding="utf-8")
    assert "delete_risk" not in source
    assert '("DELETE"' not in source and "'DELETE'" not in source


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


def test_client_writes_when_not_read_only(monkeypatch):
    client = make_client(monkeypatch, read_only=False)
    client._request("POST", "/risk/v1/risk", json={"name": "x"})
    assert client.session.requests == [("POST", "https://example.invalid/risk/v1/risk")]


# --------------------------------------------------------------------------- #
# Option matching
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw", ["Sky Bet", "sky bet", "SKY BET", "  Sky   Bet  ", "1"])
def test_uki_brand_matching_is_case_and_whitespace_insensitive(raw):
    assert risk_cli.resolve_option(raw, ["Sky Bet", "tombola"]) == "Sky Bet"


@pytest.mark.parametrize("raw", ["Phishing", "  phishing ", "PHISHING"])
def test_domain_matching_is_case_and_whitespace_insensitive(raw):
    options = risk_cli.display_options(FieldResolver(FIELDS), "Domain")
    assert risk_cli.resolve_option(raw, options) == "Phishing"


def test_domain_menu_hides_code_prefixes():
    assert risk_cli.display_options(FieldResolver(FIELDS), "Domain") == [
        "Phishing",
        "Cloud Platform Adoption",
    ]


def test_invalid_option_is_rejected():
    assert risk_cli.resolve_option("Not A Brand", ["Sky Bet"]) is None
    assert risk_cli.resolve_option("99", ["Sky Bet"]) is None


def test_multiselect_accepts_several_values_and_rejects_bad_ones(monkeypatch, capsys):
    scripted(monkeypatch, ["sky bet, nonsense", "sky bet , POKERSTARS"])
    picks = risk_cli.select_many("UKI Brand", ["Sky Bet", "tombola", "Pokerstars"])
    assert picks == ["Sky Bet", "Pokerstars"]
    assert "Not valid" in capsys.readouterr().out


def test_multiselect_enter_keeps_empty_current_selection(monkeypatch):
    scripted(monkeypatch, [""])
    assert risk_cli.select_many("CIA", ["Availability", "Confidentiality", "Integrity"], []) == []


def test_multiselect_enter_keeps_nonempty_current_selection(monkeypatch):
    scripted(monkeypatch, [""])
    assert risk_cli.select_many("CIA", ["Availability", "Confidentiality"], ["Availability"]) == [
        "Availability"
    ]


def test_multiselect_resolves_to_option_ids():
    resolver = FieldResolver(FIELDS)
    assert resolver.encode("UKI Brand", ["sky bet", "POKERSTARS"]) == (
        "f-brand",
        ["o-skybet", "o-pokerstars"],
    )


def test_unknown_option_raises():
    resolver = FieldResolver(FIELDS)
    with pytest.raises(AnecdotesError):
        resolver.encode("UKI Brand", ["Not A Brand"])


def test_decode_turns_option_ids_back_into_labels():
    resolver = FieldResolver(FIELDS)
    assert resolver.decode("UKI Brand", ["o-skybet", "o-tombola"]) == ["Sky Bet", "tombola"]
    assert resolver.decode("Domain", "o-phishing") == "CYB03 - Phishing"


def test_rating_choices_are_sorted_and_example_placeholder_is_filtered(monkeypatch, capsys):
    resolver = FieldResolver(FIELDS)
    assert risk_cli.rating_options_for(resolver, "target_impact") == ["1", "2", "3", "4", "5"]
    scripted(monkeypatch, ["5"])
    output = risk_cli.select_rating("Target impact", risk_cli.rating_options_for(resolver, "target_impact"))
    assert output == "5"
    assert "e.g." not in capsys.readouterr().out


def test_numeric_rating_labels_resolve_to_option_ids():
    resolver = FieldResolver(
        [
            {
                "id": "field-rating",
                "name": "Rating",
                "type": "SingleSelect",
                "options": [{"id": f"option-{n}", "label": f"{n} - Rating {n}"} for n in range(5, 0, -1)],
            }
        ]
    )
    assert resolver.encode("Rating", "2") == ("field-rating", "option-2")


def test_confirmed_full_field_names_resolve_exactly():
    resolver = FieldResolver(FIELDS)
    assert risk_cli.live_field_name(resolver, "operational_impact") == "Operational impact (Tech, Process, People)"
    assert risk_cli.live_field_name(resolver, "reputational_impact") == "Reputational impact (UKI)"
    assert risk_cli.live_field_name(resolver, "regulatory_legal_impact") == "Regulatory and legal impact (UKI)"
    assert risk_cli.live_field_name(resolver, "financial_impact") == "Financial impact (UKI)"


def test_exact_operational_impact_name_wins_over_similar_field():
    resolver = FieldResolver(
        FIELDS + [
            {
                "id": "f-operational-other",
                "name": "Operational impact (Technology, Process, People)",
                "type": "SingleSelect",
            }
        ]
    )
    assert risk_cli.live_field_name(resolver, "operational_impact") == "Operational impact (Tech, Process, People)"


def test_missing_exact_assessment_field_fails_closed():
    resolver = FieldResolver(FIELDS[:-1])
    with pytest.raises(AnecdotesError, match="Target likelihood"):
        risk_cli.live_field_name(resolver, "target_likelihood")

    lookalike = FieldResolver(
        [item for item in FIELDS if item.get("name") != "Operational impact (Tech, Process, People)"]
        + [{"id": "f-operational-other", "name": "Operational impact (Technology, Process, People)", "type": "SingleSelect"}]
    )
    with pytest.raises(AnecdotesError, match=r"Operational impact \(Tech, Process, People\)"):
        risk_cli.live_field_name(lookalike, "operational_impact")


def test_current_select_values_use_the_same_form_as_the_menu():
    """'TR04 - Cloud Platform Adoption' must read back as the menu label."""
    resolver = FieldResolver(FIELDS)
    current = risk_cli.read_current_values(RISK_DETAIL["risk_aaa"], resolver)
    assert current["domain"] == "Cloud Platform Adoption"
    assert current["domain"] in risk_cli.display_options(resolver, "Domain")


def test_reselecting_the_same_domain_is_not_a_change(monkeypatch, cli, capsys):
    scripted(
        monkeypatch,
        ["supplier", "1", "", "", "", "cloud platform adoption", "", ""] + [""] * 9,
    )
    assert risk_cli.main(["update"]) == 0
    assert cli.writes() == []
    assert "No changes detected. Nothing to update." in capsys.readouterr().out


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
    scripted(
        monkeypatch,
        ["supplier", "1", "", "", "New description.", "", "", "", ""] + [""] * 9,
    )
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
    assert "f-cia" in out and "o-integrity" in out
    assert "f-pii" in out and "f-target-likelihood" in out
    assert "e.g." not in out
    assert "  1   2   3   4   5" in out


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
    assert payload["fields"]["f-cia"] == [
        "o-availability",
        "o-confidentiality",
        "o-integrity",
    ]
    assert payload["fields"]["f-pii"] == "o-pii-no"
    assert payload["fields"]["f-tribe"] == ["o-gaming"]
    assert payload["fields"]["f-target-impact"] == "o-target-impact-1"
    assert payload["fields"]["f-target-likelihood"] == "o-target-likelihood-1"
    assert len(payload["fields"]) == 14
    assert "f-inherent" not in payload["fields"]
    assert payload["register_id"] == risk_cli.REGISTER_ID


def test_create_does_not_invent_a_risk_id(monkeypatch, cli, capsys):
    scripted(monkeypatch, CREATE_ANSWERS + ["y"])
    risk_cli.main(["create"])
    _, payload = cli.writes()[0]
    assert "risk_key" not in payload and "id" not in payload
    assert "risk_new123" in capsys.readouterr().out


def test_create_rejects_empty_required_text(monkeypatch):
    scripted(monkeypatch, ["", "   ", "Finally a name"])
    assert risk_cli.prompt_required("Risk name") == "Finally a name"


def test_update_can_keep_an_existing_empty_required_text_field(monkeypatch):
    scripted(monkeypatch, [""])
    assert risk_cli.prompt_required("Risk event description", "") == ""


# --------------------------------------------------------------------------- #
# Update
# --------------------------------------------------------------------------- #


def test_update_reads_risks_and_uses_internal_id(monkeypatch, cli):
    scripted(
        monkeypatch,
        ["supplier", "1", "", "sky bet,pokerstars", "Payments and withdrawals."] + [""] * 12 + ["y"],
    )
    assert risk_cli.main(["update"]) == 0
    assert ("GET", "list_risks", risk_cli.REGISTER_ID) in cli.calls
    assert ("GET", "get_risk", "risk_aaa") in cli.calls
    writes = cli.writes()
    assert len(writes) == 1
    assert writes[0][0] == "PATCH"
    assert writes[0][1] == "risk_aaa"


def test_update_payload_contains_only_changed_fields(monkeypatch, cli):
    scripted(
        monkeypatch,
        ["supplier", "1", "", "sky bet,pokerstars", "Payments and withdrawals."] + [""] * 12 + ["y"],
    )
    risk_cli.main(["update"])
    _, _, payload = cli.writes()[0]
    assert "name" not in payload, "unchanged risk name must not be patched"
    assert set(payload["fields"]) == {"f-brand", "f-desc"}
    assert payload["fields"]["f-brand"] == ["o-skybet", "o-pokerstars"]


def test_update_patches_only_changed_new_assessment_field(monkeypatch, cli):
    scripted(
        monkeypatch,
        ["supplier", "1"] + [""] * 7 + ["3"] + [""] * 7 + ["y"],
    )
    assert risk_cli.main(["update"]) == 0
    _, _, payload = cli.writes()[0]
    assert payload == {"fields": {"f-pii": "o-pii-yes"}}


def test_update_does_nothing_when_no_changes(monkeypatch, cli, capsys):
    scripted(monkeypatch, ["supplier", "1", "", "", "", "", "", ""] + [""] * 9)
    assert risk_cli.main(["update"]) == 0
    assert cli.writes() == []
    assert "No changes detected. Nothing to update." in capsys.readouterr().out


def test_update_dry_run_never_patches(monkeypatch, cli, capsys):
    scripted(
        monkeypatch,
        ["supplier", "1", "", "", "Payments and withdrawals.", "", "", ""] + [""] * 9,
    )
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
        ["supplier", "2", "", "", "Changed description."] + [""] * 12 + ["y"],
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
    scripted(monkeypatch, ["supplier", "1", "", "", "", "", "", ""] + [""] * 9)
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
        cli,
        "list_risks",
        lambda register_id=None: (_ for _ in ()).throw(AnecdotesError("denied", status_code=403)),
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
        (
            ["update", "--dry-run"],
            ["supplier", "1", "", "", "Changed.", "", "", ""] + [""] * 9,
        ),
    ],
)
def test_cli_never_writes_any_local_file(monkeypatch, cli, argv, answers):
    before = _tracked_files()
    scripted(monkeypatch, answers)
    risk_cli.main(argv)
    assert _tracked_files() == before
