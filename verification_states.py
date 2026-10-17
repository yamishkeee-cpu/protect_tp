from aiogram.fsm.state import State, StatesGroup


class Verification(StatesGroup):
    email = State()
    code = State()
    