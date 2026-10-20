import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build
from prepare_clash import prepare
from rules import accept_draft, draft_patch, explain, normalize_host
from rule_model import make_rule


def rule(kind, value, category):
    return make_rule(kind, value, category=category, source="fixture", component="fixture", source_rule=f"{kind},{value}")[0]


class OperationsTest(unittest.TestCase):
    def test_locked_fetch_rejects_tampered_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "input"
            cache.write_bytes(b"tampered")
            component = {"url": "https://raw.githubusercontent.com/example/rules/main/file", "id": "fixture", "_expected_sha256": build.sha256(b"expected")}
            with patch.object(build, "component_cache_path", return_value=cache):
                with self.assertRaisesRegex(build.BuildError, "lock"):
                    build.fetch_component("fixture", "mihomo", component, offline=True, allow_stale=False)

    def test_locked_resolution_does_not_access_moving_ref(self):
        sources = [{"id": "example", "components": {"mihomo": [{"id": "example", "url": "https://raw.githubusercontent.com/example/rules/main/file", "role": "audit-reference"}]}}]
        record = {"url": sources[0]["components"]["mihomo"][0]["url"], "role": "audit-reference", "sha256": "a" * 64, "resolved_url": "https://raw.githubusercontent.com/example/rules/" + "b" * 40 + "/file"}
        lock = {"categories": {"example": {"components": {"mihomo": {"example": record}}}}}
        with patch.object(build, "load_json", return_value=lock), patch.object(build.urllib.request, "urlopen", side_effect=AssertionError("unexpected network")):
            result = build.resolve_components(sources, locked=True)
            self.assertEqual(record["resolved_url"], result[0]["components"]["mihomo"][0]["_resolved_url"])

    def test_domain_draft_is_narrow_and_does_not_mutate_inputs(self):
        sources = [{"id": "gemini", "priority": 10}, {"id": "google", "priority": 20}]
        rules = [rule("domain-suffix", "example.com", "google")]
        original = copy.deepcopy(rules)
        draft = draft_patch("service.example.com", "gemini", "service-specific route", rules, sources)
        self.assertEqual("domain", draft["patch_document"]["patches"][0]["rule"]["type"])
        self.assertEqual("gemini", draft["routing_case"]["expected_category"])
        self.assertEqual(original, rules)
        # A later category cannot beat an earlier broad match just by adding a rule.
        with self.assertRaisesRegex(ValueError, "宽规则"):
            draft_patch("service.example.com", "google", "test", [rule("domain-suffix", "example.com", "gemini")], sources)
        with self.assertRaises(ValueError):
            normalize_host("https://example.com/?token=not-a-host")

    def test_prepared_merge_preserves_profile_and_contains_no_private_fields(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "profile.yaml"
            policies = json.loads((root / "sources/policies.json").read_text())["mihomo"]
            base = {"proxy-groups": [{"name": n} for n in set(policies.values())], "proxies": [{"name": "private-fixture", "password": "fixture-only"}], "mode": "rule", "tun": {"enable": False}, "rules": ["MATCH,DIRECT"]}
            profile.write_text(yaml.safe_dump(base))
            original = profile.read_bytes()
            fragment, report = prepare(profile, {})
            self.assertFalse(report["activated"])
            self.assertEqual(original, profile.read_bytes())
            self.assertEqual({"rule-providers", "prepend-rules"}, set(fragment))
            self.assertNotIn("fixture-only", yaml.safe_dump(fragment))
            self.assertTrue(all(k.startswith("network-rules-") for k in fragment["rule-providers"]))
            base["proxy-groups"] = []
            profile.write_text(yaml.safe_dump(base))
            with self.assertRaisesRegex(ValueError, "缺少"):
                prepare(profile, {})

    def test_explanation_tracks_patched_provenance_and_client_agreement(self):
        result = explain("ai.google.dev")
        self.assertEqual("gemini", result["canonical"]["category"])
        self.assertIn("gemini-google-overlap", result["canonical"]["patch_ids"])
        self.assertTrue(result["canonical"]["appearances"])
        self.assertEqual({"gemini"}, {v["category"] for v in result["clients"].values()})

    def test_accept_writes_patch_and_case_once_and_rejects_traversal(self):
        sources = [{"id": "gemini", "priority": 10}, {"id": "google", "priority": 20}]
        rules = [rule("domain-suffix", "example.com", "google")]
        draft = draft_patch("service.example.com", "gemini", "confirmed service", rules, sources)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("sources", "patches", "tests"):
                (root / name).mkdir()
            (root / "sources/upstreams.json").write_text(json.dumps({"sources": sources}))
            (root / "tests/routing-cases.json").write_text("[]")
            with patch("rules.load_canonical", return_value=(rules, {})):
                result = accept_draft(draft, root)
                self.assertTrue(Path(result["patch"]).exists())
                cases = json.loads((root / "tests/routing-cases.json").read_text())
                self.assertEqual([draft["routing_case"]], cases)
                with self.assertRaisesRegex(ValueError, "已存在"):
                    accept_draft(draft, root)
                invalid = copy.deepcopy(draft)
                invalid["routing_case"]["id"] = "../escape"
                with self.assertRaises(ValueError):
                    accept_draft(invalid, root)


if __name__ == "__main__":
    unittest.main()
