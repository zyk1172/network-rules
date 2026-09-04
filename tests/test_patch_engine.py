from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from patch_engine import apply_patches, resolve_priority_patches
from rule_model import make_rule


def sample_rule(rule_type, value, category):
    rule, reason = make_rule(
        rule_type,
        value,
        category=category,
        source="test",
        component="synthetic",
        source_rule=f"{rule_type},{value}",
    )
    if rule is None:
        raise AssertionError(reason)
    return rule


class PatchEngineTest(unittest.TestCase):
    def test_all_patch_actions_and_priority_resolution(self):
        candidates = [
            sample_rule("domain", "remove.example", "google"),
            sample_rule("domain", "move.example", "google"),
            sample_rule("domain", "replace.example", "google"),
            sample_rule("domain", "priority.example", "google"),
            sample_rule("domain", "priority.example", "gemini"),
        ]
        patches = [
            {
                "id": "add-rule",
                "action": "add",
                "rule": {
                    "type": "domain-suffix",
                    "value": "added.example",
                    "category": "gemini",
                },
                "reason": "test add",
            },
            {
                "id": "remove-rule",
                "action": "remove",
                "match": {"type": "domain", "value": "remove.example"},
                "reason": "test remove",
            },
            {
                "id": "reclassify-rule",
                "action": "reclassify",
                "match": {"type": "domain", "value": "move.example"},
                "from": "google",
                "to": "gemini",
                "reason": "test reclassify",
            },
            {
                "id": "replace-rule",
                "action": "replace",
                "match": {"type": "domain", "value": "replace.example"},
                "with": {
                    "type": "domain-suffix",
                    "value": "replace.example",
                    "category": "google",
                },
                "reason": "test replace",
            },
            {
                "id": "priority-rule",
                "action": "priority",
                "match": {"type": "domain", "value": "priority.example"},
                "prefer": "gemini",
                "over": ["google"],
                "reason": "test priority",
            },
        ]
        working, outcomes, priority = apply_patches(
            candidates, patches, ["google", "gemini"]
        )
        statuses = {item["id"]: item["status"] for item in outcomes}
        self.assertEqual("applied", statuses["add-rule"])
        self.assertEqual("applied", statuses["remove-rule"])
        self.assertEqual("applied", statuses["reclassify-rule"])
        self.assertEqual("applied", statuses["replace-rule"])
        self.assertEqual("pending", statuses["priority-rule"])
        self.assertEqual(5, len(working))

        selected = resolve_priority_patches(
            priority,
            outcomes,
            conflict_categories=["google", "gemini"],
            rule=sample_rule("domain", "priority.example", "google"),
        )
        self.assertEqual("priority-rule", selected["id"])
        self.assertEqual(
            "applied",
            next(item["status"] for item in outcomes if item["id"] == "priority-rule"),
        )


if __name__ == "__main__":
    unittest.main()
