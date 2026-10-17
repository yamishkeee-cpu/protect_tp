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
os.environ["ADMIN_USERNAMES"] = "Boss_User, @second_boss"
os.environ["MODERATOR_USERNAMES"] = "mod_user,1_id_admin"

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
        # any number of complaints per person is allowed, every one is stored
        self.assertEqual(admin_db.create_report(111, 110, "abuse"), "queued")
        self.assertEqual(sum(1 for r in admin_db.list_reports("n")[0] if r["target_id"] == 110), 2)
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

    # ---- admins by @username
    def test_admin_bound_by_username_case_insensitive_and_survives_rename(self):
        self.assertIsNone(admin_db.get_admin_role(500))
        self.assertIsNone(admin_db.bind_admin_by_username(500, "somebody_else"))
        self.assertIsNone(admin_db.bind_admin_by_username(500, None))
        self.assertEqual(admin_db.bind_admin_by_username(500, "BOSS_user"), "admin")
        self.assertEqual(admin_db.get_admin_role(500), "admin")
        self.assertEqual(admin_db.bind_admin_by_username(501, "mod_user"), "moderator")
        # rights are by ID afterwards: renaming does not matter
        self.assertIsNone(admin_db.bind_admin_by_username(500, "renamed_boss"))
        self.assertEqual(admin_db.get_admin_role(500), "admin")
        rows, _ = admin_db.query_journal(action="admin_bind")
        self.assertTrue(any(r["target_user_id"] == 500 and r["source"] == "auto" for r in rows))

    def test_explicit_id_admin_is_not_downgraded_by_username(self):
        # user 1 is admin by ID; an unrelated moderator username must not change that
        self.assertEqual(admin_db.bind_admin_by_username(1, "mod_user"), "admin")
        self.assertEqual(admin_db.get_admin_role(1), "admin")

    def test_removing_username_from_env_revokes_access_on_sync(self):
        self.assertEqual(admin_db.bind_admin_by_username(510, "second_boss"), "admin")
        old = os.environ["ADMIN_USERNAMES"]
        try:
            os.environ["ADMIN_USERNAMES"] = "boss_user"
            admin_db.sync_admins_from_env()
            self.assertIsNone(admin_db.get_admin_role(510))
            self.assertEqual(admin_db.get_admin_role(1), "admin")  # ID admins stay
        finally:
            os.environ["ADMIN_USERNAMES"] = old
            admin_db.sync_admins_from_env()

    def test_username_is_stored_and_updated(self):
        admin_db.ensure_account(520, "first_name")
        self.assertEqual(admin_db.ensure_account(520, "new_name")["username"], "new_name")
        self.assertEqual(admin_db.ensure_account(520)["username"], "new_name")   # omitted -> untouched
        self.assertIsNone(admin_db.ensure_account(520, None)["username"])        # person removed @username

    # ---- search by id / @username / profile name
    def test_search_by_username_name_and_id(self):
        db.save_user_profile(600, "Иван Петров", "2024", "G1", "Дизайн", "p")
        db.save_user_profile(601, "Мария Иванова", "2023", "G2", "Филология", "p")
        db.save_user_profile(602, "Пётр", "2022", "G3", "Юриспруденция", "p")
        admin_db.ensure_account(600, "ivan_hse")
        admin_db.ensure_account(601, "maria_nn")
        admin_db.ensure_account(602, None)
        ids = lambda q: [r["user_id"] for r in admin_db.search_accounts(q)[0]]
        self.assertEqual(ids("@ivan_hse"), [600])
        self.assertEqual(ids("@IVAN"), [600])                 # partial username, any case
        self.assertEqual(ids("@Иван"), [])                    # @ means username only
        self.assertEqual(set(ids("иван")), {600, 601})        # name part, Cyrillic case-insensitive
        self.assertEqual(ids("ПЕТРОВ"), [600])
        self.assertEqual(ids("пётр"), [602])
        self.assertEqual(ids("maria_nn"), [601])              # username without @ also works
        self.assertEqual(ids("600"), [600])                   # Telegram ID
        internal = admin_db.ensure_account(601)["internal_id"]
        self.assertIn(601, ids(str(internal)))                # internal ID
        self.assertEqual(admin_db.search_accounts("   "), ([], 0))
        self.assertEqual(admin_db.search_accounts("zzzzzz_none")[0], [])
        results, total = admin_db.search_accounts("иван", limit=1)
        self.assertEqual((len(results), total), (1, 2))       # total shows there are more

    def test_settings_state_text(self):
        import importlib, types
        # keyboards need aiogram; only check the pure helper's logic through SETTINGS_META here
        self.assertEqual(admin_db.SETTINGS_META["default_registered"][1], "bool")
        self.assertEqual(admin_db.SETTINGS_META["likes_per_hour"][1], "int")

    # ---- changes requested after the first review
    def test_every_complaint_is_stored_and_rebanning_after_unban_works(self):
        make_user(700, False)
        make_user(701, True)
        self.assertEqual(admin_db.create_report(701, 700, "spam"), "auto_banned")
        # more complaints against an already banned person are still stored (processed folder)
        self.assertEqual(admin_db.create_report(701, 700, "fake"), "already_banned")
        rows, total = admin_db.list_reports("d", page_size=100)
        self.assertEqual(sum(1 for r in rows if r["target_id"] == 700), 2)
        # unban, then the same reporter can ban again
        admin_db.unban_user(700, 1)
        self.assertIsNone(admin_db.active_ban(admin_db.ensure_account(700)))
        self.assertEqual(admin_db.create_report(701, 700, "spam"), "auto_banned")
        self.assertIsNotNone(admin_db.active_ban(admin_db.ensure_account(700)))

    def test_ban_follows_the_account_not_the_profile(self):
        make_user(710, True)
        admin_db.ban_user(710, None, "Нарушение правил", 1, "comment")
        db.save_user_profile(710, "New name", "2025", "G9", "Филология", "new-photo")  # profile re-created
        self.assertIsNotNone(admin_db.active_ban(admin_db.ensure_account(710)))
        make_user(711, True)
        self.assertNotIn(710, {db.get_random_stranger(711)[0] for _ in range(20)} - {None})

    def test_unverified_ban_is_lifted_by_registration_verified_ban_is_not(self):
        make_user(720, False)
        admin_db.ban_user(720, 30, "Нарушение правил", 1, "c")     # manual ban of an unverified account
        self.assertTrue(admin_db.set_registered(720, True, None, source="auto"))
        self.assertIsNone(admin_db.active_ban(admin_db.ensure_account(720)))
        admin_db.ban_user(720, 30, "Нарушение правил", 1, "c")     # now verified: registration does not matter
        self.assertFalse(admin_db.set_registered(720, True, 1))
        self.assertIsNotNone(admin_db.active_ban(admin_db.ensure_account(720)))

    def test_ban_notice_has_reason_and_comment_but_no_report_number(self):
        make_user(730, True)
        make_user(731, True)
        admin_db.create_report(731, 730, "spam")
        rid = next(r["id"] for r in admin_db.list_reports("n")[0] if r["target_id"] == 730)
        res = admin_db.resolve_report(rid, 1, "temp_ban", "Рассылка рекламы", 7)
        self.assertEqual(res["reason"], "Спам")
        details = admin_db.last_ban_details(730)
        self.assertEqual((details["reason"], details["comment"]), ("Спам", "Рассылка рекламы"))
        self.assertNotIn("#", details["reason"])
        make_user(732, False)
        admin_db.create_report(731, 732, "abuse")
        self.assertNotIn("#", admin_db.last_ban_details(732)["reason"])

    def test_limit_blocks_the_action_for_an_hour_and_clear_button_lifts_it(self):
        admin_db.set_setting("likes_per_hour", "2", 1)
        try:
            first = [admin_db.check_and_record_action(740, "like") for _ in range(2)]
            self.assertEqual(first, [None, None])
            blocked = admin_db.check_and_record_action(740, "like")
            self.assertIn("заблокировано до", blocked)
            # still blocked even if the limit is raised: the 1 hour block is in force
            admin_db.set_setting("likes_per_hour", "50", 1)
            self.assertIsNotNone(admin_db.check_and_record_action(740, "like"))
            # other actions are not affected
            self.assertIsNone(admin_db.check_and_record_action(740, "skip"))
            blocks, _ = admin_db.clear_all_restrictions(1)
            self.assertGreaterEqual(blocks, 1)
            self.assertIsNone(admin_db.check_and_record_action(740, "like"))
        finally:
            admin_db.set_setting("likes_per_hour", "30", 1)

    def test_clear_all_restrictions_lifts_access_restriction(self):
        make_user(750, True)
        admin_db.restrict_user(750, 30, "test")
        _, restrictions = admin_db.clear_all_restrictions(1)
        self.assertGreaterEqual(restrictions, 1)
        self.assertIsNone(admin_db.active_restriction(admin_db.ensure_account(750)))

    def test_old_reports_table_with_unique_constraint_is_migrated(self):
        import subprocess
        path = os.path.join(_tmp.name, "old_reports.db")
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
                reason TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'new',
                decision TEXT, moderator_id INTEGER, moderator_comment TEXT NOT NULL DEFAULT '',
                target_was_registered INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, reviewed_at TEXT,
                UNIQUE (reporter_id, target_id));
            INSERT INTO reports (reporter_id, target_id, reason, created_at) VALUES (1, 2, 'spam', '2026-10-14 10:00:00');
        """)
        old.commit()
        old.close()
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "import db, admin_db\n"
            "with db.db_connection() as c:\n"
            "    c.execute(\"INSERT INTO reports (reporter_id, target_id, reason, created_at) VALUES (1, 2, 'spam', 'x')\")\n"
            "    print(c.execute('SELECT COUNT(*) FROM reports').fetchone()[0])\n"
        ) % str(Path(__file__).resolve().parent.parent)
        result = subprocess.run([sys.executable, "-c", code], env=dict(os.environ, DATABASE_PATH=path),
                                capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "2", result.stderr)


if __name__ == "__main__":
    unittest.main()
