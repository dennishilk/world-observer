"""Offline checks for the standalone WoW Forever collector."""
import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts/collect_wow_forever.py"
spec = importlib.util.spec_from_file_location("wow_forever_collector", MODULE)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "name": "Dennis", "surname": "Hilk",
            "level": 14, "experience": 6863,
            "average_item_level": 7, "last_login_timestamp": 1794310232000
        }
        self.gear = {"equipped_items": [{
            "slot": {"name": "Brust"}, "name": "Kampfkettentunika",
            "level": {"value": 13}, "key": {"href": "ignored"}
        }]}
        self.jobs = {"primaries": [{
            "profession": {"name": "Enchanting"},
            "tiers": [{"skill_points": 2, "max_skill_points": 75,
                       "known_recipes": [{"name": "should not export"}]}]
        }], "secondaries": []}

    def test_snapshot_only_public_allowlisted_fields(self):
        result = collector.snapshot(self.profile, self.gear, self.jobs,
                                    datetime(2026, 11, 10, 12, tzinfo=timezone.utc))
        self.assertEqual(result["character"]["level"], 14)
        self.assertEqual(result["equipment"], [
            {"slot": "Brust", "name": "Kampfkettentunika", "item_level": 13}])
        self.assertEqual(result["professions"], [{
            "name": "Enchanting", "skill_points": 2, "max_skill_points": 75}])
        self.assertEqual(result["expires_at"], "2026-11-17T12:00:00Z")
        self.assertNotIn("known_recipes", str(result))
        self.assertNotIn("href", str(result))

    def test_identity_and_level_validation(self):
        bad = dict(self.profile, surname="Other")
        with self.assertRaises(collector.CollectorError):
            collector.snapshot(bad, self.gear, self.jobs, datetime.now(timezone.utc))
        bad = dict(self.profile, level=True)
        with self.assertRaises(collector.CollectorError):
            collector.snapshot(bad, self.gear, self.jobs, datetime.now(timezone.utc))

    def test_credentials_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credentials"
            path.write_text("id\nsecret\n", encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(collector.credentials(path), ("id", "secret"))
            path.chmod(0o644)
            with self.assertRaises(collector.CollectorError):
                collector.credentials(path)


if __name__ == "__main__":
    unittest.main()
