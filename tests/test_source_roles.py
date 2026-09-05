from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build import BuildError, merge_client_category_rules, validate_manifest
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


def sample_manifest(authoritative_role="canonical-authoritative"):
    return {
        "schema_version": 2,
        "publication": {"repository": "zyk1172/network-rules", "ref": "main"},
        "sources": [
            {
                "id": "example",
                "category": "Example",
                "priority": 10,
                "enabled": True,
                "provider": "example/rules",
                "homepage": "https://github.com/example/rules",
                "license": "Example-License",
                "components": {
                    "quantumult-x": [
                        {
                            "id": "example-qx",
                            "url": "https://raw.githubusercontent.com/example/rules/main/example.list",
                            "format": "qx-list",
                            "role": authoritative_role,
                        }
                    ],
                    "mihomo": [
                        {
                            "id": "example-mihomo",
                            "url": "https://raw.githubusercontent.com/example/rules/main/example.yaml",
                            "format": "mihomo-yaml",
                            "behavior": "classical",
                            "role": "audit-reference",
                        }
                    ],
                },
            }
        ],
    }


class SourceRoleTest(unittest.TestCase):
    def test_each_category_requires_one_authoritative_component(self):
        policies = {"quantumult-x": {"example": "direct"}, "mihomo": {"example": "DIRECT"}}
        sources, _categories = validate_manifest(sample_manifest(), policies)
        self.assertEqual("canonical-authoritative", sources[0]["components"]["quantumult-x"][0]["role"])

        invalid = sample_manifest()
        invalid["sources"][0]["components"]["mihomo"][0]["role"] = "canonical-authoritative"
        with self.assertRaises(BuildError):
            validate_manifest(invalid, policies)

    def test_client_only_extra_is_explicitly_scoped(self):
        authority = [sample_rule("domain-suffix", "example.com", "example")]
        extra = [sample_rule("process-name", "com.example.App", "example")]

        qx_rules, qx_canonical, qx_extra, _unsupported = merge_client_category_rules(
            authority, [], client="quantumult-x"
        )
        mihomo_rules, mihomo_canonical, mihomo_extra, _unsupported = merge_client_category_rules(
            authority, extra, client="mihomo"
        )

        self.assertEqual(1, len(qx_rules))
        self.assertEqual(1, qx_canonical)
        self.assertEqual(0, qx_extra)
        self.assertEqual(2, len(mihomo_rules))
        self.assertEqual(1, mihomo_canonical)
        self.assertEqual(1, mihomo_extra)
        self.assertEqual("process-name", mihomo_rules[-1].type)


if __name__ == "__main__":
    unittest.main()
