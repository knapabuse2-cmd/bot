"""
FSM states for admin bot.

Defines states for multi-step operations like:
- Adding accounts
- Creating campaigns
- Configuring settings
"""

from aiogram.fsm.state import State, StatesGroup


class AccountStates(StatesGroup):
    """States for account management."""

    # Search
    waiting_search_query = State()

    # Adding account via session file
    waiting_session_file = State()
    waiting_phone_for_session = State()

    # Adding account via phone auth
    waiting_phone = State()
    waiting_code = State()
    waiting_2fa = State()

    # Adding account via ZIP archive (tdata)
    waiting_zip_proxy = State()  # Select proxy before uploading ZIP
    waiting_zip_file = State()
    waiting_zip_2fa = State()  # If 2FA needed during validation

    # Bulk import (multiple session+json pairs in one ZIP)
    waiting_bulk_zip_file = State()

    # Bulk import from multiple archives (each archive = folder with json+session)
    waiting_multi_archive_count = State()  # How many accounts to import
    waiting_multi_archive_files = State()

    # Re-authorization (for imported accounts)
    waiting_reauth_2fa = State()

    # Customization (avatar, name, bio)
    waiting_customize_name = State()
    waiting_customize_bio = State()
    waiting_customize_avatar = State()

    # Settings
    waiting_limits = State()

    # Premium purchase - card input
    waiting_card_number = State()
    waiting_card_expiry = State()
    waiting_card_cvc = State()


class CampaignStates(StatesGroup):
    """States for campaign management."""

    # Creating campaign
    waiting_name = State()
    waiting_description = State()

    # Configuring goal
    waiting_goal_message = State()
    waiting_goal_url = State()
    waiting_goal_min_messages = State()
    waiting_goal_max_messages = State()

    # Configuring prompt
    waiting_system_prompt = State()
    waiting_first_message = State()
    waiting_forbidden_topics = State()

    # AI settings
    waiting_ai_model = State()
    waiting_ai_temperature = State()
    waiting_ai_max_tokens = State()

    # Sending settings (batch first messages)
    waiting_send_interval = State()      # Interval in hours
    waiting_messages_per_batch = State()  # Number of messages per batch
    waiting_message_delay = State()       # Delay range (min,max in seconds)

    # Loading targets
    waiting_targets_file = State()

    # Assigning accounts
    selecting_accounts = State()

    # Bulk account limits update
    waiting_bulk_max_conversations = State()


class ProxyStates(StatesGroup):
    """States for proxy management."""
    
    # Adding proxies
    waiting_proxy_list = State()
    waiting_proxy_single = State()


class DialogueStates(StatesGroup):
    """States for dialogue viewing."""

    viewing_dialogue = State()
    waiting_manual_message = State()


class ScraperStates(StatesGroup):
    """States for target scraping."""

    # Selecting account for scraping
    selecting_account = State()

    # Uploading channel list
    waiting_channels_file = State()

    # Selecting campaign for targets (optional)
    selecting_campaign = State()

    # Scraping in progress
    scraping = State()


class TelegramAppStates(StatesGroup):
    """States for Telegram API app management."""

    # Adding new app
    waiting_api_id = State()
    waiting_api_hash = State()
    waiting_name = State()
    waiting_max_accounts = State()

    # Editing
    waiting_edit_name = State()
    waiting_edit_max_accounts = State()


class ProxyGroupStates(StatesGroup):
    """States for proxy group management."""

    # Creating group
    waiting_name = State()
    waiting_description = State()
    waiting_country_code = State()

    # Adding proxies to group
    waiting_proxy_list = State()

    # Editing group
    waiting_edit_name = State()
    waiting_edit_description = State()
