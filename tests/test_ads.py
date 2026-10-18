"""Ad delivery regressions; no Telegram connection required."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.core import db
from app.features.admin import admin_db, ads, admin_handlers
from app.features.profile import handlers
from app.features.admin.admin_states import AdEdit


class AdTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(db, "DB_PATH", Path(self.tmp.name) / "ads.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        db.init_db()
        admin_db.init_admin_db()

    def campaign(self, every=3, limit=None, start=None, end=None):
        ad_id = admin_db.create_ad(1, "Test", None, "https://example.com", "Go",
                                   every, limit, start, end)
        admin_db.set_ad_active(ad_id, True, 1)
        return ad_id

    async def test_frequency_per_user_and_limit(self):
        ad_id = self.campaign(limit=2)
        target = SimpleNamespace(answer=AsyncMock())
        for i in range(9):
            await ads.maybe_show_ad(target, 100)
            self.assertEqual(target.answer.await_count, min((i + 1) // 3, 2))
        await ads.maybe_show_ad(target, 101)
        self.assertEqual(target.answer.await_count, 2)
        self.assertEqual(admin_db.ad_stats(ad_id)["impressions"], 2)

    async def test_failed_ad_does_not_reset_counter(self):
        ad_id = self.campaign(every=1)
        target = SimpleNamespace(answer=AsyncMock(side_effect=RuntimeError("offline")))
        with self.assertLogs(ads.logger, level="ERROR"):
            await ads.maybe_show_ad(target, 100)
        self.assertEqual(admin_db.ad_stats(ad_id)["impressions"], 0)
        with admin_db._conn() as conn:
            self.assertEqual(conn.execute("SELECT counter FROM user_ad_state").fetchone()[0], 1)
        target.answer.side_effect = None
        await ads.maybe_show_ad(target, 100)
        self.assertEqual(admin_db.ad_stats(ad_id)["impressions"], 1)

    async def test_concurrent_profiles_respect_limit(self):
        ad_id = self.campaign(every=1, limit=1)
        target = SimpleNamespace(answer=AsyncMock())
        await asyncio.gather(*(ads.maybe_show_ad(target, 100) for _ in range(5)))
        self.assertEqual(target.answer.await_count, 1)
        self.assertEqual(admin_db.ad_stats(ad_id)["impressions"], 1)

    async def test_broken_photos_count_only_delivered_profile(self):
        ad_id = self.campaign(every=2)
        target = SimpleNamespace(answer_photo=AsyncMock(side_effect=[
            TelegramBadRequest(method="sendPhoto", message="bad photo"), None,
        ]), answer=AsyncMock())
        candidates = [(1, "A", "2024", "G", "F", "bad"),
                      (2, "B", "2024", "G", "F", "good")]
        with patch.object(handlers, "get_random_stranger", side_effect=candidates), \
             patch.object(handlers, "mark_stranger_viewed"), \
             patch.object(handlers, "get_user_bio", return_value=""):
            await handlers.send_random_profile(target, 100)
        self.assertEqual(target.answer_photo.await_count, 2)
        self.assertEqual(admin_db.ad_stats(ad_id)["impressions"], 0)
        await ads.maybe_show_ad(target, 100)
        self.assertEqual(admin_db.ad_stats(ad_id)["impressions"], 1)

    async def test_empty_feed_does_not_count(self):
        self.campaign(every=1)
        target = SimpleNamespace(answer=AsyncMock())
        with patch.object(handlers, "get_random_stranger", return_value=None), \
             patch.object(handlers, "reset_all_viewed"):
            await handlers.send_random_profile(target, 100)
        with admin_db._conn() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM user_ad_state").fetchone()[0], 0)

    async def test_dates_and_disabled_campaigns(self):
        future = self.campaign(every=1, start="2999-01-01")
        expired = self.campaign(every=1, end="2000-01-01")
        disabled = self.campaign(every=1)
        admin_db.set_ad_active(disabled, False, 1)
        self.assertIsNone(admin_db.next_ad_for_user(100))
        self.assertIn("начала", admin_db.ad_status_label(admin_db.get_ad(future)))
        self.assertIn("завершена", admin_db.ad_status_label(admin_db.get_ad(expired)))

    async def test_deleted_slot_is_unavailable_and_logged(self):
        ad_id = self.campaign(every=1)
        admin_db.record_impression(ad_id, 100)
        self.assertTrue(admin_db.delete_ad(ad_id, 1))
        self.assertFalse(admin_db.delete_ad(ad_id, 1))
        self.assertIsNone(admin_db.get_ad(ad_id))
        self.assertEqual(admin_db.list_ads(), [])
        self.assertIsNone(admin_db.next_ad_for_user(100))
        rows, total = admin_db.query_journal(action="ad_delete")
        self.assertEqual(total, 1)
        self.assertEqual(admin_db.ad_stats(ad_id)["impressions"], 1)
        call = SimpleNamespace(data=f"ad_click_{ad_id}", answer=AsyncMock())
        await ads.ad_click(call)
        call.answer.assert_awaited_once_with("Реклама недоступна", show_alert=True)

    async def test_moderator_cannot_delete(self):
        ad_id = self.campaign()
        call = SimpleNamespace(data=f"adm:addeleteconfirm:{ad_id}",
                               from_user=SimpleNamespace(id=2))
        with patch.object(admin_handlers, "_role", return_value="moderator"), \
             patch.object(admin_handlers, "_deny", new_callable=AsyncMock) as deny:
            await admin_handlers.cb_ad_delete_confirm(call)
        deny.assert_awaited_once()
        self.assertIsNotNone(admin_db.get_ad(ad_id))

    def edit_state(self):
        return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))

    async def test_edit_all_fields_preserves_stats_status_and_counter(self):
        ad_id = self.campaign(every=1)
        admin_db.record_impression(ad_id, 100)
        admin_db.record_click(ad_id, 100)
        admin_db.next_ad_for_user(100)
        original = admin_db.get_ad(ad_id)
        values = dict(text="Updated", image="new_photo", url="https://example.org/new",
                      button_text="Visit", every_n=10, max_per_user=5,
                      start_date="2026-01-01", end_date="2026-12-31")
        for field, value in values.items():
            self.assertTrue(admin_db.update_ad_field(ad_id, field, value, 1))
        updated = admin_db.get_ad(ad_id)
        for field, value in values.items():
            self.assertEqual(updated[field], value)
        for field in ("id", "is_active", "created_at", "created_by"):
            self.assertEqual(updated[field], original[field])
        self.assertEqual(admin_db.ad_stats(ad_id)["impressions"], 1)
        self.assertEqual(admin_db.ad_stats(ad_id)["clicks"], 1)
        with admin_db._conn() as conn:
            self.assertEqual(conn.execute("SELECT counter FROM user_ad_state").fetchone()[0], 1)
        self.assertEqual(admin_db.query_journal(action="ad_edit")[1], 8)

    async def test_invalid_edits_do_not_change_slot(self):
        ad_id = self.campaign(start="2026-01-01", end="2026-12-31")
        original = admin_db.get_ad(ad_id)
        invalid = [("every_n", 0), ("every_n", 1001), ("max_per_user", -1),
                   ("text", ""), ("button_text", "x" * 31), ("url", "http://example.com"),
                   ("start_date", "2027-01-01"), ("end_date", "2025-12-31"),
                   ("start_date", "2026-02-30"), ("is_active", 0)]
        for field, value in invalid:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                admin_db.update_ad_field(ad_id, field, value, 1)
        self.assertEqual(admin_db.get_ad(ad_id), original)

    async def test_edit_input_validation_then_save(self):
        ad_id = self.campaign()
        state = self.edit_state()
        await state.set_state(AdEdit.value)
        await state.update_data(ad_id=ad_id, field="every_n")
        message = SimpleNamespace(from_user=SimpleNamespace(id=1), text="0", answer=AsyncMock())
        with patch.object(admin_handlers, "_role", return_value="admin"):
            await admin_handlers.ad_edit_value(message, state)
            self.assertEqual(await state.get_state(), AdEdit.value.state)
            self.assertEqual(admin_db.get_ad(ad_id)["every_n"], 3)
            message.text = "7"
            await admin_handlers.ad_edit_value(message, state)
        self.assertEqual(admin_db.get_ad(ad_id)["every_n"], 7)
        self.assertIsNone(await state.get_state())

    async def test_clear_photo_and_dates_and_unlimit(self):
        ad_id = self.campaign(limit=1, start="2026-01-01", end="2026-12-31")
        admin_db.update_ad_field(ad_id, "image", "photo", 1)
        for field in ("image", "start_date", "end_date"):
            state = self.edit_state()
            await state.set_state(AdEdit.value)
            await state.update_data(ad_id=ad_id, field=field)
            call = SimpleNamespace(from_user=SimpleNamespace(id=1), answer=AsyncMock())
            with patch.object(admin_handlers, "_role", return_value="admin"), \
                 patch.object(admin_handlers, "_show", new_callable=AsyncMock):
                await admin_handlers.cb_ad_edit_clear(call, state)
            self.assertIsNone(admin_db.get_ad(ad_id)[field])
            self.assertIsNone(await state.get_state())
        admin_db.update_ad_field(ad_id, "max_per_user", 0, 1)
        self.assertIsNone(admin_db.get_ad(ad_id)["max_per_user"])

    async def test_cancel_edit_does_not_change_slot(self):
        ad_id = self.campaign()
        original = admin_db.get_ad(ad_id)
        state = self.edit_state()
        await state.set_state(AdEdit.value)
        await state.update_data(ad_id=ad_id, field="text")
        call = SimpleNamespace(data=f"adm:adedit:{ad_id}",
                               from_user=SimpleNamespace(id=1), answer=AsyncMock())
        with patch.object(admin_handlers, "_role", return_value="admin"), \
             patch.object(admin_handlers, "_show", new_callable=AsyncMock):
            await admin_handlers.cb_ad_edit(call, state)
        self.assertIsNone(await state.get_state())
        self.assertEqual(await state.get_data(), {})
        self.assertEqual(admin_db.get_ad(ad_id), original)

    async def test_edit_deleted_slot_does_not_recreate_it(self):
        ad_id = self.campaign()
        state = self.edit_state()
        await state.set_state(AdEdit.value)
        await state.update_data(ad_id=ad_id, field="text")
        admin_db.delete_ad(ad_id, 1)
        message = SimpleNamespace(from_user=SimpleNamespace(id=1), text="Updated", answer=AsyncMock())
        with patch.object(admin_handlers, "_role", return_value="admin"):
            await admin_handlers.ad_edit_value(message, state)
        self.assertIsNone(admin_db.get_ad(ad_id))
        self.assertIsNone(await state.get_state())
        message.answer.assert_awaited_once_with("Кампания уже удалена.")

    async def test_moderator_cannot_edit_or_clear(self):
        ad_id = self.campaign()
        state = self.edit_state()
        await state.update_data(ad_id=ad_id, field="image")
        call = SimpleNamespace(from_user=SimpleNamespace(id=2))
        message = SimpleNamespace(from_user=SimpleNamespace(id=2))
        with patch.object(admin_handlers, "_role", return_value="moderator"), \
             patch.object(admin_handlers, "_deny", new_callable=AsyncMock) as deny:
            await admin_handlers.cb_ad_edit(call, state)
            await admin_handlers.cb_ad_edit_field(call, state)
            await admin_handlers.cb_ad_edit_clear(call, state)
            await admin_handlers.ad_edit_value(message, state)
        self.assertEqual(deny.await_count, 3)
        self.assertEqual(admin_db.query_journal(action="ad_edit")[1], 0)
