"""Тесты подтверждения почты. Работают на временной базе, рабочую не трогают."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import db
from app.features.verification import verification_db as vdb
from app.features.verification import verification_service as vs


class DomainTests(unittest.TestCase):
    def test_allowed(self):
        for email in ("Ivanov@edu.hse.ru", "  a.b@hse.ru ", "ab_1@EDU.HSE.RU", "a-b@hse.ru"):
            self.assertTrue(vs.is_allowed_email(email), email)

    def test_rejected(self):
        for email in ("", "a@evil.com", "a@hse.ru.evil.com", "a@mail.hse.ru", "a@spb.hse.ru",
                      "a@xedu.hse.ru", "a@nothse.ru", "a@@hse.ru", "@hse.ru", "a b@hse.ru",
                      "a@hse.ru\nbcc:x@y.z", "a+1@hse.ru", "a#b@hse.ru", "a@hse.ru@evil.com",
                      "a@edu.hse.ru.", "hse.ru", "я@hse.ru"):
            self.assertFalse(vs.is_allowed_email(email), repr(email))


class VerificationBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_path = db.DB_PATH
        db.DB_PATH = Path(tmp.name) / "test.db"
        self.addCleanup(setattr, db, "DB_PATH", old_path)
        db.init_db()

        env = mock.patch.dict(os.environ, {"EMAIL_HASH_SECRET": "s" * 32, "EMAIL_DEV_MODE": "1"})
        env.start()
        self.addCleanup(env.stop)

        self.sent = []
        patcher = mock.patch.object(
            vs, "_send_email_sync", side_effect=lambda to, code: self.sent.append((to, code))
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        cooldown = mock.patch.object(vs, "RESEND_COOLDOWN_SECONDS", 0)
        cooldown.start()
        self.addCleanup(cooldown.stop)

    def make_user(self, user_id):
        db.save_user(user_id, "Имя", "2024", "Гр-1", "Факультет", "photo_id")

    def wrong_code(self):
        return "000000" if self.sent[-1][1] != "000000" else "111111"


class StatusTests(VerificationBase):
    def test_default_and_transitions(self):
        self.assertEqual(vdb.get_user_status(999), "guest")
        self.make_user(1)
        self.assertEqual(vdb.get_user_status(1), "guest")
        self.assertTrue(vdb.set_status(1, "verified"))
        self.assertEqual(vdb.get_user_status(1), "verified")
        self.assertTrue(vdb.set_status(1, "banned"))
        self.assertEqual(vdb.get_user_status(1), "banned")
        self.assertFalse(vdb.set_status(999, "verified"))
        with self.assertRaises(ValueError):
            vdb.set_status(1, "admin")

    def test_reregistration_keeps_status(self):
        self.make_user(1)
        vdb.set_status(1, "verified")
        self.make_user(1)  # «Заполнить заново»
        self.assertEqual(vdb.get_user_status(1), "verified")


class FlowTests(VerificationBase):
    async def test_full_flow(self):
        self.make_user(1)
        res = await vs.request_code(1, "Ivanov@edu.hse.ru")
        self.assertEqual(res.status, "sent")
        self.assertEqual(self.sent[-1][0], "ivanov@edu.hse.ru")
        res = await vs.verify_code(1, self.wrong_code())
        self.assertEqual((res.status, res.attempts_left), ("wrong_code", 4))
        res = await vs.verify_code(1, self.sent[-1][1])
        self.assertEqual(res.status, "verified")
        self.assertEqual(vdb.get_user_status(1), "verified")
        # код одноразовый
        self.assertEqual((await vs.verify_code(1, self.sent[-1][1])).status, "no_code")

    async def test_no_profile_and_bad_domain(self):
        self.assertEqual((await vs.request_code(5, "a@hse.ru")).status, "no_profile")
        self.make_user(5)
        self.assertEqual((await vs.request_code(5, "a@gmail.com")).status, "invalid_domain")
        self.assertEqual(self.sent, [])

    async def test_bad_format_does_not_spend_attempt(self):
        self.make_user(1)
        await vs.request_code(1, "a@hse.ru")
        self.assertEqual((await vs.verify_code(1, "12ab")).status, "bad_format")
        res = await vs.verify_code(1, self.wrong_code())
        self.assertEqual(res.attempts_left, 4)

    async def test_attempts_exhausted(self):
        self.make_user(1)
        await vs.request_code(1, "a@hse.ru")
        bad = self.wrong_code()
        for _ in range(4):
            self.assertEqual((await vs.verify_code(1, bad)).status, "wrong_code")
        self.assertEqual((await vs.verify_code(1, bad)).status, "too_many_attempts")
        # правильный код после исчерпания уже не работает
        self.assertEqual((await vs.verify_code(1, self.sent[-1][1])).status, "no_code")
        self.assertEqual(vdb.get_user_status(1), "guest")

    async def test_expired(self):
        self.make_user(1)
        with mock.patch.object(vs, "CODE_TTL_MINUTES", -1):
            await vs.request_code(1, "a@hse.ru")
        self.assertEqual((await vs.verify_code(1, self.sent[-1][1])).status, "expired")

    async def test_new_code_invalidates_old(self):
        self.make_user(1)
        await vs.request_code(1, "a@hse.ru")
        old = self.sent[-1][1]
        await vs.request_code(1, "a@hse.ru")
        new = self.sent[-1][1]
        if old != new:
            self.assertEqual((await vs.verify_code(1, old)).status, "wrong_code")
        self.assertEqual((await vs.verify_code(1, new)).status, "verified")


class LimitTests(VerificationBase):
    async def test_cooldown(self):
        self.make_user(1)
        with mock.patch.object(vs, "RESEND_COOLDOWN_SECONDS", 60):
            self.assertEqual((await vs.request_code(1, "a@hse.ru")).status, "sent")
            res = await vs.request_code(1, "a@hse.ru")
        self.assertEqual(res.status, "cooldown")
        self.assertGreater(res.retry_after, 0)

    async def test_daily_limit(self):
        self.make_user(1)
        with mock.patch.object(vs, "MAX_REQUESTS_PER_DAY", 2):
            self.assertEqual((await vs.request_code(1, "a@hse.ru")).status, "sent")
            self.assertEqual((await vs.request_code(1, "a@hse.ru")).status, "sent")
            self.assertEqual((await vs.request_code(1, "a@hse.ru")).status, "daily_limit")

    async def test_failed_send_does_not_burn_limit(self):
        self.make_user(1)
        with mock.patch.object(vs, "_send_email_sync", side_effect=OSError("smtp down")):
            self.assertEqual((await vs.request_code(1, "a@hse.ru")).status, "send_failed")
        self.assertEqual(vdb.count_requests_since(1, "2000-01-01 00:00:00"), 0)


class EmailBindingTests(VerificationBase):
    async def _verify(self, user_id, email):
        await vs.request_code(user_id, email)
        return await vs.verify_code(user_id, self.sent[-1][1])

    async def test_one_email_one_account(self):
        self.make_user(1)
        self.make_user(2)
        self.assertEqual((await self._verify(1, "a@hse.ru")).status, "verified")
        # другой аккаунт: почта занята (регистр не важен)
        self.assertEqual((await vs.request_code(2, "A@HSE.RU")).status, "email_taken")
        # тот же аккаунт может подтвердить повторно
        vdb.set_status(1, "banned")
        # ранее верифицированный забаненный не может снять бан подтверждением почты
        self.assertEqual((await vs.request_code(1, "a@hse.ru")).status, "banned")
        self.assertEqual(vdb.get_user_status(1), "banned")

    async def test_taken_attempts_count_in_limit(self):
        self.make_user(1)
        self.make_user(2)
        await self._verify(1, "a@hse.ru")
        with mock.patch.object(vs, "MAX_REQUESTS_PER_DAY", 2):
            self.assertEqual((await vs.request_code(2, "a@hse.ru")).status, "email_taken")
            self.assertEqual((await vs.request_code(2, "a@hse.ru")).status, "email_taken")
            self.assertEqual((await vs.request_code(2, "a@hse.ru")).status, "daily_limit")

    async def test_race_on_complete(self):
        """Если почту заняли между отправкой и вводом кода, привязка не проходит."""
        self.make_user(1)
        self.make_user(2)
        await vs.request_code(2, "a@hse.ru")
        code2 = self.sent[-1][1]
        await self._verify(1, "a@hse.ru")
        self.assertEqual((await vs.verify_code(2, code2)).status, "email_taken")
        self.assertEqual(vdb.get_user_status(2), "guest")


class StorageTests(VerificationBase):
    async def test_no_plaintext_email_or_code_in_db(self):
        self.make_user(1)
        await vs.request_code(1, "secret.person@edu.hse.ru")
        code = self.sent[-1][1]
        conn = db.connect_db()
        try:
            dump = "\n".join(conn.iterdump())
        finally:
            conn.close()
        self.assertNotIn("secret.person", dump)
        self.assertNotIn(f"'{code}'", dump)

    async def test_missing_secret(self):
        self.make_user(1)
        with mock.patch.dict(os.environ, {"EMAIL_HASH_SECRET": ""}):
            self.assertEqual((await vs.request_code(1, "a@hse.ru")).status, "config_error")


if __name__ == "__main__":
    unittest.main()