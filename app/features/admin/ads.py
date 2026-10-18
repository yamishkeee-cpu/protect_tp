"""Ad cards shown between profiles in the main feed, plus click tracking."""
import html
import logging
import asyncio
from weakref import WeakValueDictionary

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.features.admin import admin_db

logger = logging.getLogger(__name__)
ads_router = Router()
_delivery_locks = WeakValueDictionary()


def ad_caption(ad: dict) -> str:
    # The "Реклама" label is mandatory: users must see it is not a real profile.
    return f"📢 <b>Реклама</b>\n\n{html.escape(ad['text'])}"


async def send_ad_card(target: Message, ad: dict, preview: bool = False) -> None:
    """Send an ad as its own card. In preview mode the button does nothing harmful."""
    callback = "adm:noop" if preview else f"ad_click_{ad['id']}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=ad["button_text"], callback_data=callback)]
    ])
    if ad.get("image"):
        await target.answer_photo(photo=ad["image"], caption=ad_caption(ad), reply_markup=keyboard)
    else:
        await target.answer(ad_caption(ad), reply_markup=keyboard)


async def maybe_show_ad(target: Message, user_id: int) -> None:
    """Called once after a delivered feed profile. Serialize delivery per user."""
    lock = _delivery_locks.setdefault(user_id, asyncio.Lock())
    try:
        async with lock:
            ad = admin_db.next_ad_for_user(user_id)
            if not ad:
                return
            await send_ad_card(target, ad)
            admin_db.record_impression(ad["id"], user_id)
    except Exception:
        logger.exception("Ad delivery failed for user %s", user_id)


@ads_router.callback_query(F.data.startswith("ad_click_"))
async def ad_click(call: types.CallbackQuery):
    try:
        ad_id = int(call.data.split("_", 2)[2])
    except (ValueError, IndexError):
        await call.answer()
        return
    ad = admin_db.get_ad(ad_id)
    if not ad:
        await call.answer("Реклама недоступна", show_alert=True)
        return
    admin_db.record_click(ad_id, call.from_user.id)
    await call.answer()
    try:
        await call.message.answer(
            "Ссылка рекламодателя (откроется во внешнем браузере):",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Перейти", url=ad["url"])]
            ]),
        )
    except TelegramAPIError:
        logger.warning("Could not send ad link for ad %s", ad_id)
