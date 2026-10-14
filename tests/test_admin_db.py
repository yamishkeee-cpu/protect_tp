"""Tests for the admin panel data layer (temporary database, no Telegram)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = os.path.join(_tmp.name, "test.db")
os.environ["ADMIN_IDS"] = "1"
os.environ["MODERATOR_IDS"] = "2"

import sqlite3  # noqa: E402

import admin_db  # noqa: E402
import db  # noqa: E402


def make_user(uid, registered):
    db.save_user_profile(uid, f"User{uid}", "2024", "G1", "Дизайн", "photo")
    admin_db.ensure_account(uid)
    admin_db.set_registered(uid, registered, 1)


class AdminDbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        admin_db.sync_admins_from_env()

    def test_roles(self):
        self.assertEqual(admin_db.get_admin_role(1), "admin")
        self.assertEqual(admin_db.get_admin_role(2), "moderator")
        self.assertIsNone(admin_db.get_admin_role(999))

    def test_report_on_unregistered_bans_instantly_and_hides_from_feed(self):
        make_user(100, False)
        make_user(101, True)
        make_user(102, True)
        self.assertEqual(admin_db.create_report(101, 100, "spam"), "auto_banned")
        ban = admin_db.active_ban(admin_db.ensure_account(100))
        self.assertTrue(ban and ban["permanent"])
        seen = {db.get_random_stranger(102)[0] for _ in range(30)}
        self.assertNotIn(100, seen)
        rows, _ = admin_db.query_journal(user_id=100)
        self.assertEqual(rows[0]["source"], "auto")
        self.assertIsNone(rows[0]["admin_id"])

    def test_report_on_registered_goes_to_moderator_without_ban(self):
        make_user(110, True)
        make_user(111, True)
        self.assertEqual(admin_db.create_report(111, 110, "abuse"), "queued")
        self.assertIsNone(admin_db.active_ban(admin_db.ensure_account(110)))
        rows, total = admin_db.list_reports("n")
        report = next(r for r in rows if r["target_id"] == 110)
        self.assertEqual(admin_db.create_report(111, 110, "abuse"), "duplicate")
        result = admin_db.resolve_report(report["id"], 2, "temp_ban", "ok", 7)
        self.assertEqual(result["decision"], "temp_ban")
        self.assertIsNotNone(admin_db.active_ban(admin_db.ensure_account(110)))
        self.assertIsNone(admin_db.resolve_report(report["id"], 2, "dismiss"))  # already processed

    def test_dismiss_keeps_user_unbanned(self):
        make_user(120, True)
        make_user(121, True)
        admin_db.create_report(121, 120, "fake")
        rid = next(r["id"] for r in admin_db.list_reports("n")[0] if r["target_id"] == 120)
        admin_db.resolve_report(rid, 1, "dismiss", "не нарушение")
        self.assertIsNone(admin_db.active_ban(admin_db.ensure_account(120)))

    def test_admin_cannot_be_banned_or_reported(self):
        make_user(130, True)
        with self.assertRaises(ValueError):
            admin_db.ban_user(2, 1, "x", 1)
        db.save_user_profile(1, "Admin", "2020", "G", "Дизайн", "p")
        self.assertEqual(admin_db.create_report(130, 1, "spam"), "invalid")

    def test_becoming_registered_lifts_auto_ban_only(self):
        make_user(140, False)
        make_user(141, True)
        admin_db.create_report(141, 140, "spam")
        self.assertIsNotNone(admin_db.active_ban(admin_db.ensure_account(140)))
        self.assertTrue(admin_db.set_registered(140, True, None, source="auto"))
        self.assertIsNone(admin_db.active_ban(admin_db.ensure_account(140)))
        # a manual ban must stay
        admin_db.ban_user(140, None, "manual", 1)
        self.assertFalse(admin_db.set_registered(140, True, 1))
        self.assertIsNotNone(admin_db.active_ban(admin_db.ensure_account(140)))

    def test_find_account_by_telegram_and_internal_id(self):
        make_user(150, True)
        acc = admin_db.find_account("150")
        self.assertEqual(acc["user_id"], 150)
        self.assertEqual(admin_db.find_account(str(acc["internal_id"]))["user_id"] in (150, acc["user_id"]), True)
        self.assertIsNone(admin_db.find_account("abc"))
        self.assertIsNone(admin_db.find_account("987654321"))

    def test_journal_is_append_only(self):
        admin_db.set_setting("likes_per_hour", "40", 1)
        with db.db_connection() as conn:
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("UPDATE admin_actions SET reason = 'x'")
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("DELETE FROM admin_actions")
        admin_db.set_setting("likes_per_hour", "30", 1)

    def test_settings_validation(self):
        with self.assertRaises(ValueError):
            admin_db.set_setting("likes_per_hour", "0", 1)
        with self.assertRaises(ValueError):
            admin_db.set_setting("nonexistent", "1", 1)

    def test_like_limit(self):
        admin_db.set_setting("likes_per_hour", "3", 1)
        results = [admin_db.check_and_record_action(160, "like") for _ in range(4)]
        admin_db.set_setting("likes_per_hour", "30", 1)
        self.assertEqual(results[:3], [None, None, None])
        self.assertIsNotNone(results[3])
        self.assertIsNone(admin_db.check_and_record_action(160, "unknown"))

    def test_restriction(self):
        make_user(170, True)
        admin_db.restrict_user(170, 5, "test")
        self.assertIsNotNone(admin_db.active_restriction(admin_db.ensure_account(170)))

    def test_ads_frequency_limit_dates_and_stats(self):
        make_user(180, True)
        ad_id = admin_db.create_ad(1, "text", None, "https://example.com/x", "Go", 3, 2, None, None)
        self.assertIsNone(admin_db.next_ad_for_user(180))  # inactive
        admin_db.set_ad_active(ad_id, True, 1)
        make_user(181, True)  # fresh counter: the inactive call above already counted one profile for 180
        shown = []
        for _ in range(12):
            ad = admin_db.next_ad_for_user(181)
            shown.append(bool(ad))
            if ad:
                admin_db.record_impression(ad["id"], 181)
        for _ in range(2):  # 180 saw ads only through the loop above in the real feed; keep stats simple
            admin_db.record_impression(ad_id, 180)
        # every 3rd profile, at most 2 impressions per user
        self.assertEqual(shown, [False, False, True, False, False, True] + [False] * 6)
        admin_db.record_click(ad_id, 180)
        stats = admin_db.ad_stats(ad_id)
        self.assertEqual((stats["impressions"], stats["clicks"]), (4, 1))
        expired = admin_db.create_ad(1, "old", None, "https://example.com", "Go", 1, None, None, "2000-01-01")
        admin_db.set_ad_active(expired, True, 1)
        self.assertEqual(admin_db.ad_status_label(admin_db.get_ad(expired)), "⌛ завершена")

    def test_ad_url_validation(self):
        v = admin_db.validate_ad_url
        self.assertIsNone(v("https://hse.ru/promo?x=1"))
        for bad in ("http://hse.ru", "https://bit.ly/abc", "https://127.0.0.1/x", "https://user:pw@hse.ru",
                    "javascript:alert(1)", "https://no-dot", "https://a b.ru"):
            self.assertIsNotNone(v(bad), bad)

    def test_events_and_temp_profiles_of_banned_hidden(self):
        import events_db
        import temp_profile_db
        make_user(190, True)
        make_user(191, True)
        event_id = events_db.create_event_full(190, "Поход", "2099-01-01", "2099-01-02", None, 1, 3, "d", "l")
        ids = {e[0] for e in events_db.get_active_events_for_search(191, 10)}
        self.assertIn(event_id, ids)
        admin_db.ban_user(190, 1, "test", 1)
        ids = {e[0] for e in events_db.get_active_events_for_search(191, 10)}
        self.assertNotIn(event_id, ids)
        self.assertTrue(all(row[8] != 190 for row in
                            [db.get_active_temp_profiles_for_search(191) or (0,)*9 for _ in range(10)]))


if __name__ == "__main__":
    unittest.main()
