"""FSM states for comment bot admin."""

from aiogram.fsm.state import State, StatesGroup


class AccountStates(StatesGroup):
    """States for account management."""

    waiting_phone = State()        # Waiting for phone number
    waiting_code = State()         # Waiting for SMS/Telegram code
    waiting_2fa = State()          # Waiting for 2FA password
    waiting_tdata = State()        # Waiting for tdata file


class CommentStates(StatesGroup):
    """States for comment operations."""

    waiting_channel = State()      # Waiting for channel link
    waiting_post = State()         # Waiting for post selection
    waiting_text = State()         # Waiting for comment text
