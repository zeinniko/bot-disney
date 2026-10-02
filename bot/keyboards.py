from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="🔑 Change Password Only",
                callback_data="btn_chpass_only",
                style="success",
            )
        ],
        [
            InlineKeyboardButton(
                text="🔑 Change Password + 📱 Signout All Devices",
                callback_data="btn_chpass_signout",
                style="primary",
            )
        ],
        [
            InlineKeyboardButton(
                text="📱 Lookup / Kick Device",
                callback_data="btn_lookup_kick",
                style="danger",
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="✖️ Batal / Pilih Menu Lain",
                callback_data="btn_cancel",
                style="danger",
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_stop_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="🛑 Stop Proses",
                callback_data=f"btn_stop_{chat_id}",
                style="danger",
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_main_menu_button() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text="🏠 Main Menu",
                callback_data="btn_cancel",
                style="primary",
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)