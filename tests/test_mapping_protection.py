import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from protect_mapping import is_allowed


def test_mapping_change_only_allowed_for_expected_bot_branch():
    assert is_allowed("github-actions[bot]", "automation/anecdotes-map", "github-actions[bot]")
    assert is_allowed("github-actions[bot]", "automation/anecdotes-map-123", "github-actions[bot]")
    assert not is_allowed("alice", "automation/anecdotes-map-123", "github-actions[bot]")
    assert not is_allowed("github-actions[bot]", "feature/manual-edit", "github-actions[bot]")
