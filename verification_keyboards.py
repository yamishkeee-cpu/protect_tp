from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

VERIFY_CALLBACK = "verify_email_start"
SKIP_VERIFY_CALLBACK = "verify_email_skip"
BACK_CALLBACK = "verify_email_back"


def get_verify_keyboard(text: str = "✉️ Подтвердить почту") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=VERIFY_CALLBACK)]]
    )


def get_skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text="➡️ Продолжить без верификации", callback_data=SKIP_VERIFY_CALLBACK
        )]]
    )

def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=BACK_CALLBACK)]]
    )