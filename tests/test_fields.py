import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from anecdotes_client import FieldResolver


def test_field_and_option_matching_are_case_insensitive():
    fields = [
        {
            "id": "field-brand",
            "name": "UKI Brand",
            "type": "MultiSelect",
            "options": [
                {"id": "a", "label": "Sky Bet"},
                {"id": "b", "label": "Pokerstars"},
            ],
        }
    ]
    resolver = FieldResolver(fields)
    field_id, value = resolver.encode("uki BRAND", ["sky bet", "POKERSTARS"])
    assert field_id == "field-brand"
    assert value == ["a", "b"]


def test_free_text_is_preserved():
    fields = [{"id": "field-text", "name": "Impacted asset/s", "type": "FreeText"}]
    resolver = FieldResolver(fields)
    field_id, value = resolver.encode("IMPACTED ASSET/S", "Payments platform")
    assert field_id == "field-text"
    assert value == "Payments platform"


def test_string_options_are_supported():
    fields = [
        {
            "id": "field-brand",
            "name": "UKI Brand",
            "type": "MultiSelect",
            "options": ["Sky Bet", "Pokerstars"],
        }
    ]
    resolver = FieldResolver(fields)
    field_id, value = resolver.encode("UKI Brand", ["sky bet", "POKERSTARS"])
    assert field_id == "field-brand"
    assert value == ["Sky Bet", "Pokerstars"]


def test_nested_string_options_are_supported():
    fields = [
        {
            "id": "field-brand",
            "name": "UKI Brand",
            "type": "MultiSelect",
            "metadata": {
                "configuration": {
                    "selectOptions": ["Sky Bet", "Pokerstars"],
                }
            },
        }
    ]
    resolver = FieldResolver(fields)
    field_id, value = resolver.encode("UKI Brand", ["sky bet", "POKERSTARS"])
    assert field_id == "field-brand"
    assert value == ["Sky Bet", "Pokerstars"]
