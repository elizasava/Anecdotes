import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import canonical_choice, normalize


def test_normalize_is_case_and_space_insensitive():
    assert normalize("  SKY   Bet ") == normalize("sky bet")


def test_canonical_choice_ignores_case():
    assert canonical_choice("POKERSTARS", ["Pokerstars"], "brand") == "Pokerstars"
