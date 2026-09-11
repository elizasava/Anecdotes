import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from risk_io import validate_risk


def test_risk_values_are_canonicalized_case_insensitively():
    risk = {
        "risk_key": "risk-001",
        "risk_name": "Supplier outage",
        "uki_brand": ["SKY BET", "pokerstars"],
        "risk_event_description": "Description",
        "domain": "third party & outsourcing risk",
        "context_background": "Background",
        "impacted_assets": "Payments",
    }
    result = validate_risk(risk)
    assert result["risk_key"] == "RISK-001"
    assert result["uki_brand"] == ["Sky Bet", "Pokerstars"]
    assert result["domain"] == "Third Party & Outsourcing Risk"
