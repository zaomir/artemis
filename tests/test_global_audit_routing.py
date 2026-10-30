from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
OPENING = "Вы создаёте новый аудит? Ответьте на вопросы."


class GlobalAuditRoutingTest(unittest.TestCase):
    def test_artemis_applies_pre_router_before_property_context(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        cursor = (ROOT / ".cursorrules").read_text(encoding="utf-8")
        for content in (agents, cursor):
            self.assertIn("Multi-Location Growth Score", content)
            self.assertIn("Growth Score", content)
            self.assertIn("аудит", content)
            self.assertIn(OPENING, content)
        self.assertLess(agents.index("Universal Growth Score audit pre-router"), agents.index("Artemis context"))


if __name__ == "__main__":
    unittest.main()
