"""Regression tests for the SQLite layer; they need no Telegram token/network."""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_TEMP_DIR = tempfile.TemporaryDirectory(prefix="protect_tp_tests_")
os.environ["DATABASE_PATH"] = str(Path(_TEMP_DIR.name) / "test.db")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
import events_db  # noqa: E402
from temp_profile_db import save_temp_profile_with_partial_fill  # noqa: E402


class DatabaseRegressionTests(unittest.TestCase):
    def setUp(self):
        if db.DB_PATH.exists():
            db.DB_PATH.unlink()
        db.init_db()
        db.save_user(101, "Анна", "2024", "БИ-101", "Компьютерные науки", "photo_a")
        db.save_user(202, "Борис", "2023", "ПИ-202", "Программная инженерия", "photo_b")
        db.save_user(303, "Вера", "2022", "Э-303", "Экономика", "photo_c")

    def test_relative_database_path_resolves_beside_the_module(self):
        expected = Path(db.__file__).resolve().parent / "alternate.db"
        self.assertEqual(db._resolve_db_path("alternate.db"), expected)
        absolute = Path(_TEMP_DIR.name) / "alternate.db"
        self.assertEqual(db._resolve_db_path(str(absolute)), absolute)

    def test_profiles_are_saved_to_both_legacy_and_current_tables(self):
        self.assertEqual(db.get_user(101), db.get_user_profile(101))
        self.assertEqual(db.get_user_profile(101)[0], "Анна")

    def test_profile_view_history_is_per_user(self):
        stranger = db.get_random_stranger(101)
        self.assertIsNotNone(stranger)
        db.mark_stranger_viewed(101, stranger[0])
        self.assertNotEqual(db.get_random_stranger(101)[0], stranger[0])
        # The same profile must remain visible to another user.
        self.assertIsNotNone(db.get_random_stranger(202))

    def test_legacy_user_rows_migrate_to_permanent_profiles(self):
        with db.db_connection() as conn:
            conn.execute(
                "INSERT INTO users (user_id, name, start_year, group_num, faculty, photo, viewed) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (404, "Гость", "2025", "КН-404", "Филология", "photo_404"),
            )
        db.init_db()
        self.assertEqual(db.get_user_profile(404), ("Гость", "2025", "КН-404", "Филология", "photo_404"))

    def test_likes_are_deduplicated(self):
        self.assertTrue(db.add_like(101, 202))
        self.assertFalse(db.add_like(101, 202))
        self.assertTrue(db.has_like(101, 202))
        self.assertFalse(db.has_like(202, 101))

    def test_temp_profile_inherits_fields_but_respects_explicit_skip(self):
        temp_id = save_temp_profile_with_partial_fill(
            101,
            {
                "goal": "ищу_людей",
                "name": None,          # inherit name
                "start_year": None,    # inherit year
                "group_num": "",      # explicitly skip group
                "faculty": None,       # inherit faculty
                "photo": None,         # inherit photo
                "description": "Ищу команду",
            },
        )
        row = db.get_temp_profile_by_id(temp_id)
        self.assertEqual(row[2], "Анна")
        self.assertEqual(row[3], "2024")
        self.assertEqual(row[4], "")
        self.assertEqual(row[5], "Компьютерные науки")
        self.assertEqual(row[6], "photo_a")

    def test_event_capacity_duplicate_response_and_owner_access(self):
        category_id = events_db.get_event_categories_by_type()[0][0]
        event_date = (date.today() + timedelta(days=2)).isoformat()
        event_id = events_db.create_event_full(
            101, "Учебный проект", event_date, event_date, None,
            category_id, 1, "Нужен участник", "Кампус",
        )
        response_id = events_db.add_event_response(event_id, 202)
        self.assertIsNotNone(response_id)
        self.assertIsNone(events_db.add_event_response(event_id, 202))
        self.assertEqual(events_db.get_responses_count(event_id), 1)
        self.assertEqual(events_db.get_event_detail(event_id)[10], "closed")
        self.assertEqual(len(events_db.get_event_responses_list(event_id, 101)), 1)
        self.assertEqual(events_db.get_event_responses_list(event_id, 202), [])
        self.assertEqual(events_db.get_active_events_for_search(303), [])

    def test_event_date_validation(self):
        category_id = events_db.get_event_categories_by_type()[0][0]
        start = (date.today() + timedelta(days=3)).isoformat()
        end = (date.today() + timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):
            events_db.create_event_full(101, "Неправильная дата", start, end, None,
                                        category_id, None, "", "")

    def test_event_requires_participant_count_and_links_search_profile(self):
        category_id = events_db.get_event_categories_by_type()[0][0]
        event_date = (date.today() + timedelta(days=2)).isoformat()
        with self.assertRaises(ValueError):
            events_db.create_event_full(101, "Без лимита", event_date, event_date, None,
                                        category_id, None, "", "")
        event_id = events_db.create_event_full(101, "Мероприятие с анкетой", event_date, event_date, None,
                                               category_id, 3, "Описание", "Кампус")
        detail = events_db.get_event_detail(event_id)
        self.assertEqual(detail[7], 3)
        with db.db_connection() as conn:
            row = conn.execute("SELECT participant_profile_id FROM events WHERE id = ?", (event_id,)).fetchone()
            self.assertIsNotNone(row[0])
            profile = conn.execute("SELECT event_id, goal FROM temp_profiles WHERE id = ?", (row[0],)).fetchone()
            self.assertEqual(profile, (event_id, "ищу_людей"))
        searchable = db.get_active_temp_profiles_for_search(202)
        self.assertEqual(searchable[9], event_id)
        self.assertEqual(searchable[10], "Мероприятие с анкетой")


if __name__ == "__main__":
    unittest.main()
