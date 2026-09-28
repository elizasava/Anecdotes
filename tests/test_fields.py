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


def test_code_prefixed_labels_match_human_readable_values():
    fields = [
        {
            "id": "field-domain",
            "name": "Domain",
            "type": "DropDown",
            "field_metadata": {
                "values": {
                    "149bfc4c-67f3-489c-8072-2b4a751aaa73": "CYB01 - Malware Event (Ransomware/Spyware)",
                    "2b4e05f7-2245-43c7-90ec-a7a5ae276b74": "TR3 - Cloud Platform Adoption",
                }
            },
        }
    ]
    resolver = FieldResolver(fields)
    field_id, value = resolver.encode("Domain", "Cloud Platform Adoption")
    assert field_id == "field-domain"
    assert value == "2b4e05f7-2245-43c7-90ec-a7a5ae276b74"
