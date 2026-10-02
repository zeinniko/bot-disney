from aiogram.fsm.state import State, StatesGroup


class MenuState(StatesGroup):
    chpass_only = State()
    chpass_signout = State()
    lookup_kick = State()