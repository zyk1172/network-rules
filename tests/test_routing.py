from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from routing import run_routing_cases


class RoutingCasesTest(unittest.TestCase):
    def test_representative_cases_match_both_clients(self):
        results, failures = run_routing_cases()
        self.assertTrue(results, "routing-cases.json 不应为空")
        self.assertEqual([], failures, f"语义路由案例失败：{failures}")


if __name__ == "__main__":
    unittest.main()
