"""
Telegram Worker Client.

Enhanced client for human-like Telegram interactions:
- Read receipts (mark messages as read)
- Typing indicators
- Natural message sending
"""

import asyncio
from typing import Callable, Optional, Union
from pathlib import Path

import structlog
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.messages import (
    ReadHistoryRequest,
    SetTypingRequest,
    ReadMentionsRequest,
)
from telethon.tl.types import (
    SendMessageTypingAction,
    SendMessageCancelAction,
    User,
    InputPeerUser,
    Channel,
    Chat,
    Message as TelegramMessage,
)
from telethon.tl.functions.channels import (
    JoinChannelRequest,
    LeaveChannelRequest,
    GetParticipantsRequest,
)
from telethon.tl.types import ChannelParticipantsRecent, ChannelParticipantsSearch
from telethon.tl.functions.messages import (
    ImportChatInviteRequest,
    CheckChatInviteRequest,
)
from telethon.errors import (
    FloodWaitError,
    UserPrivacyRestrictedError,
    UserNotMutualContactError,
    ChatWriteForbiddenError,
    PeerFloodError,
)

from src.config import get_settings
from src.domain.exceptions import (
    TelegramAuthError,
    TelegramFloodError,
    TelegramPrivacyError,
    TelegramUserNotFoundError,
)
from src.utils.crypto import get_session_encryption
from src.infrastructure.telegram.device_fingerprint import (
    DeviceFingerprint,
    generate_fingerprint_for_account,
    generate_fingerprint_with_app_update,
)

logger = structlog.get_logger(__name__)


class TelegramWorkerClient:
    """
    Telegram client for worker accounts.
    
    Provides human-like interaction capabilities:
    - Reading messages (marks as read)
    - Typing indicators
    - Natural delays between actions
    """
    
    def __init__(
        self,
        account_id: str,
        session_data: Optional[bytes] = None,
        session_path: Optional[str] = None,
        proxy_config: Optional[dict] = None,
        device_fingerprint: Optional[DeviceFingerprint] = None,
        lang_code: Optional[str] = None,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
    ):
        """
        Initialize worker client.

        Args:
            account_id: Account identifier
            session_data: Encrypted session bytes
            session_path: Path to session file (alternative to session_data)
            proxy_config: Proxy configuration dict
            device_fingerprint: Optional custom device fingerprint
            lang_code: Optional language code for fingerprint generation
            api_id: Optional Telegram API ID (uses settings if not provided)
            api_hash: Optional Telegram API hash (uses settings if not provided)
        """
        self._account_id = account_id
        self._session_data = session_data
        self._session_path = session_path
        self._proxy_config = proxy_config
        self._client: Optional[TelegramClient] = None
        self._connected = False
        self._message_handler: Optional[Callable] = None
        self._settings = get_settings()

        # API credentials - use provided or fall back to settings
        self._api_id = api_id
        self._api_hash = api_hash

        # Generate or use provided device fingerprint
        # Each account gets a unique fingerprint with periodic app "updates"
        # to simulate normal user behavior
        if device_fingerprint:
            self._fingerprint = device_fingerprint
        else:
            # Use fingerprint with app update simulation
            # Device stays consistent, app version may change ~10% of days
            self._fingerprint = generate_fingerprint_with_app_update(
                account_id=account_id,
                lang_code=lang_code,
                update_probability=0.1,  # 10% chance of "updated" app per day
            )

        logger.debug(
            "Device fingerprint generated",
            account_id=account_id,
            device=self._fingerprint.device_model,
            system=self._fingerprint.system_version,
            app=self._fingerprint.app_version,
        )
    
    @property
    def connected(self) -> bool:
        """Check if client is connected."""
        return self._connected and self._client is not None
    
    @property
    def client(self) -> Optional[TelegramClient]:
        """Get underlying Telethon client."""
        return self._client
    
    async def connect(self) -> None:
        """Connect to Telegram."""
        if self._connected:
            return
        
        # Prepare session
        session = await self._prepare_session()

        # Get API credentials - use provided or fall back to settings
        api_id = self._api_id or self._settings.telegram.api_id
        api_hash = self._api_hash or self._settings.telegram.api_hash.get_secret_value()

        # Create client with unique device fingerprint
        self._client = TelegramClient(
            session,
            api_id=api_id,
            api_hash=api_hash,
            proxy=self._proxy_config,
            # Device fingerprint - makes each account look like a unique device
            device_model=self._fingerprint.device_model,
            system_version=self._fingerprint.system_version,
            app_version=self._fingerprint.app_version,
            lang_code=self._fingerprint.lang_code,
            system_lang_code=self._fingerprint.system_lang_code,
        )
        
        try:
            await self._client.connect()
            
            if not await self._client.is_user_authorized():
                raise TelegramAuthError("Session not authorized")
            
            self._connected = True

            # Register message handler if set
            if self._message_handler:
                self._register_handler()

            logger.info(
                "Telegram client connected",
                account_id=self._account_id,
                device=self._fingerprint.device_model,
                system=self._fingerprint.system_version,
            )
            
        except Exception as e:
            self._connected = False
            logger.error(
                "Telegram connection failed",
                account_id=self._account_id,
                error=str(e),
            )
            raise TelegramAuthError(str(e))
    
    async def disconnect(self) -> None:
        """Disconnect from Telegram."""
        if self._client:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.warning("Disconnect error", error=str(e))
            finally:
                self._connected = False
                self._client = None
    
    async def _prepare_session(self) -> Union[str, Path, StringSession]:
        """Prepare session for connection."""
        if self._session_path:
            return self._session_path

        if self._session_data:
            # Decrypt session data (may be a SQLite session DB *or* a Telethon StringSession)
            encryption = get_session_encryption()
            decrypted = encryption.decrypt(self._session_data)

            # 1) SQLite session file (default Telethon format)
            # SQLite files start with: b"SQLite format 3\x00"
            if decrypted.startswith(b"SQLite format 3\x00"):
                # Convert SQLite session to StringSession for compatibility
                # Some sessions (e.g., from opentele) have extra columns that
                # are incompatible with Telethon's expected format
                return await self._sqlite_to_string_session(decrypted)

            # 2) StringSession (base64-like string, often starts with "1")
            # Do NOT write it to a ".session" file (it is not SQLite).
            try:
                session_str = decrypted.decode().strip()
            except Exception:
                session_str = decrypted.decode("utf-8", errors="ignore").strip()

            if not session_str:
                raise ValueError("Decrypted session is empty")

            return StringSession(session_str)

        raise ValueError("No session data or path provided")

    async def _sqlite_to_string_session(self, sqlite_data: bytes) -> StringSession:
        """
        Convert SQLite session data to StringSession.

        This handles sessions that may have extra columns (e.g., from opentele)
        that are incompatible with Telethon's expected 5-column format.
        """
        import sqlite3
        import tempfile
        import os
        import struct
        import base64
        from telethon.crypto import AuthKey

        # Write SQLite data to temp file
        with tempfile.NamedTemporaryFile(suffix='.session', delete=False) as f:
            f.write(sqlite_data)
            temp_path = f.name

        try:
            conn = sqlite3.connect(temp_path)
            cursor = conn.cursor()

            # Read session data - only the columns we need
            cursor.execute('SELECT dc_id, server_address, port, auth_key FROM sessions LIMIT 1')
            row = cursor.fetchone()

            if not row:
                raise ValueError("No session data in SQLite file")

            dc_id, server_address, port, auth_key = row

            conn.close()

            # Ensure auth_key is 256 bytes
            if isinstance(auth_key, bytes) and len(auth_key) == 256:
                # Create a StringSession and set its internal state
                session = StringSession()
                session.set_dc(dc_id, server_address, port)
                session.auth_key = AuthKey(data=auth_key)

                # Save and return new StringSession
                session_string = session.save()
                return StringSession(session_string)
            else:
                raise ValueError(f"Invalid auth_key length: {len(auth_key) if isinstance(auth_key, bytes) else 'not bytes'}")

        finally:
            os.unlink(temp_path)
    
    # =========================================
    # Reading Messages
    # =========================================
    
    async def mark_as_read(
        self,
        user_id: int | str,
        max_id: int = 0,
    ) -> bool:
        """
        Mark messages as read.
        
        Sends read receipt to user, showing "seen" status.
        
        Args:
            user_id: User to mark messages from
            max_id: Mark messages up to this ID (0 = all)
            
        Returns:
            True if successful
        """
        if not self._client:
            return False
        
        try:
            peer = await self._client.get_input_entity(user_id)
            
            await self._client(ReadHistoryRequest(
                peer=peer,
                max_id=max_id,
            ))
            
            logger.debug(
                "Messages marked as read",
                account_id=self._account_id,
                user_id=user_id,
            )
            return True
            
        except Exception as e:
            logger.warning(
                "Failed to mark as read",
                user_id=user_id,
                error=str(e),
            )
            return False
    
    async def read_and_wait(
        self,
        user_id: int | str,
        message_ids: list[int],
        reading_time: float,
    ) -> None:
        """
        Simulate reading messages.
        
        Marks as read, then waits (simulating reading time).
        
        Args:
            user_id: User who sent messages
            message_ids: Message IDs to mark as read
            reading_time: Seconds to "read"
        """
        if message_ids:
            max_id = max(message_ids)
            await self.mark_as_read(user_id, max_id)
        
        # Simulate reading
        await asyncio.sleep(reading_time)
    
    # =========================================
    # Typing Indicator
    # =========================================
    
    async def start_typing(self, user_id: int) -> bool:
        """
        Send typing indicator.
        
        Shows "typing..." to the user.
        
        Args:
            user_id: User to show typing to
            
        Returns:
            True if successful
        """
        if not self._client:
            return False
        
        try:
            peer = await self._client.get_input_entity(user_id)
            
            await self._client(SetTypingRequest(
                peer=peer,
                action=SendMessageTypingAction(),
            ))
            
            return True
            
        except Exception as e:
            logger.debug("Typing indicator failed", error=str(e))
            return False
    
    async def stop_typing(self, user_id: int) -> bool:
        """
        Cancel typing indicator.
        
        Args:
            user_id: User to cancel typing for
            
        Returns:
            True if successful
        """
        if not self._client:
            return False
        
        try:
            peer = await self._client.get_input_entity(user_id)
            
            await self._client(SetTypingRequest(
                peer=peer,
                action=SendMessageCancelAction(),
            ))
            
            return True
            
        except Exception:
            return False
    
    async def type_and_wait(
        self,
        user_id: int | str,
        typing_time: float,
    ) -> None:
        """
        Show typing indicator for specified time.
        
        Automatically refreshes typing every 5 seconds
        (Telegram typing expires after ~5-6 seconds).
        
        Args:
            user_id: User to show typing to
            typing_time: Total seconds to show typing
        """
        if typing_time <= 0:
            return
        
        elapsed = 0.0
        refresh_interval = 4.5  # Refresh before expiry
        
        while elapsed < typing_time:
            await self.start_typing(user_id)
            
            wait_time = min(refresh_interval, typing_time - elapsed)
            await asyncio.sleep(wait_time)
            elapsed += wait_time
        
        # Don't explicitly stop - let it expire naturally
    
    # =========================================
    # Sending Messages
    # =========================================
    
    async def send_message(
        self,
        user_id: int | str,
        text: str,
        reply_to: Optional[int] = None,
    ) -> Optional[int]:
        """
        Send a message.
        
        Args:
            user_id: User/entity to send to
            text: Message text
            reply_to: Optional message ID to reply to
            
        Returns:
            Message ID if sent, None on failure
            
        Raises:
            TelegramFloodError: Rate limited
            TelegramPrivacyError: User has privacy restrictions
        """
        if not self._client:
            return None
        
        try:
            message = await self._client.send_message(
                user_id,
                text,
                reply_to=reply_to,
            )
            
            logger.debug(
                "Message sent",
                account_id=self._account_id,
                user_id=user_id,
                message_id=message.id,
            )
            
            return message.id
            
        except FloodWaitError as e:
            logger.warning(
                "Flood wait",
                account_id=self._account_id,
                seconds=e.seconds,
            )
            raise TelegramFloodError(e.seconds)
            
        except (UserPrivacyRestrictedError, UserNotMutualContactError) as e:
            logger.info(
                "User privacy restriction",
                account_id=self._account_id,
                user_id=user_id,
            )
            raise TelegramPrivacyError(str(e))
            
        except ChatWriteForbiddenError as e:
            logger.warning(
                "Write forbidden",
                account_id=self._account_id,
                user_id=user_id,
            )
            raise TelegramPrivacyError(str(e))
            
        except PeerFloodError as e:
            logger.warning(
                "Peer flood - account rate limited by Telegram",
                account_id=self._account_id,
            )
            raise TelegramFloodError(3600)  # Wait 1 hour
            
        except Exception as e:
            logger.error(
                "Send message failed",
                account_id=self._account_id,
                user_id=user_id,
                error=str(e),
            )
            return None
    
    async def send_message_natural(
        self,
        user_id: int | str,
        text: str,
        typing_time: float,
        reply_to: Optional[int] = None,
    ) -> Optional[int]:
        """
        Send message with typing simulation.
        
        Shows typing indicator, waits, then sends.
        
        Args:
            user_id: User/entity to send to
            text: Message text
            typing_time: Seconds to show typing before sending
            reply_to: Optional message ID to reply to
            
        Returns:
            Message ID if sent
        """
        # Show typing
        await self.type_and_wait(user_id, typing_time)
        
        # Send message
        return await self.send_message(user_id, text, reply_to)
    
    async def send_messages_natural(
        self,
        user_id: int | str,
        messages: list[str],
        typing_times: list[float],
        pause_between: float = 1.5,
    ) -> list[int]:
        """
        Send multiple messages naturally.
        
        Simulates human sending multiple messages in sequence.
        
        Args:
            user_id: User/entity to send to
            messages: List of message texts
            typing_times: Typing time for each message
            pause_between: Pause between messages
            
        Returns:
            List of sent message IDs
        """
        sent_ids = []
        
        for i, (text, typing_time) in enumerate(zip(messages, typing_times)):
            # Typing and send
            msg_id = await self.send_message_natural(
                user_id,
                text,
                typing_time,
            )
            
            if msg_id:
                sent_ids.append(msg_id)
            
            # Pause before next message (except last)
            if i < len(messages) - 1:
                # Small random variation in pause
                actual_pause = pause_between * (0.7 + 0.6 * asyncio.get_event_loop().time() % 1)
                await asyncio.sleep(actual_pause)
        
        return sent_ids
    
    # =========================================
    # User Info
    # =========================================
    
    async def get_user_id(self, username: str) -> Optional[int]:
        """
        Resolve username to user ID.
        
        Args:
            username: Telegram username (without @)
            
        Returns:
            User ID if found
        """
        if not self._client:
            return None
        
        try:
            entity = await self._client.get_entity(username)
            if isinstance(entity, User):
                return entity.id
            return None
        except ValueError:
            return None
        except FloodWaitError as e:
            raise TelegramFloodError(e.seconds)
    
    async def get_user_info(self, user_id: int) -> Optional[dict]:
        """
        Get user information.
        
        Args:
            user_id: User ID
            
        Returns:
            Dict with user info
        """
        if not self._client:
            return None
        
        try:
            entity = await self._client.get_entity(user_id)
            if isinstance(entity, User):
                return {
                    "id": entity.id,
                    "username": entity.username,
                    "first_name": entity.first_name,
                    "last_name": entity.last_name,
                    "phone": entity.phone,
                    "bot": entity.bot,
                }
            return None
        except Exception:
            return None
    
    # =========================================
    # Message Handler
    # =========================================
    
    def on_message(self, handler: Callable) -> None:
        """
        Register incoming message handler.
        
        Handler signature: async def handler(
            user_id: int | str,
            username: Optional[str],
            text: str,
            message_id: int,
        )
        
        Args:
            handler: Async callback function
        """
        self._message_handler = handler
        
        if self._connected:
            self._register_handler()
    
    def _register_handler(self) -> None:
        """Register handler with Telethon."""
        if not self._client or not self._message_handler:
            return

        @self._client.on(events.NewMessage(incoming=True))
        async def handler(event):
            # Only handle private messages
            if not event.is_private:
                return

            sender = await event.get_sender()
            if not isinstance(sender, User) or sender.bot:
                return

            # Get message text, handling stickers and media
            text = event.message.text or ""

            # Handle stickers - convert to descriptive text for AI
            if event.message.sticker:
                # Get sticker emoji if available
                sticker_emoji = getattr(event.message.sticker, 'alt', '') or ''
                if sticker_emoji:
                    text = f"[стикер: {sticker_emoji}]"
                else:
                    text = "[стикер]"

            # Handle other media types
            elif not text:
                if event.message.photo:
                    text = "[фото]"
                elif event.message.video:
                    text = "[видео]"
                elif event.message.voice:
                    text = "[голосовое сообщение]"
                elif event.message.video_note:
                    text = "[видеосообщение]"
                elif event.message.gif:
                    text = "[гифка]"
                elif event.message.document:
                    text = "[файл]"

            await self._message_handler(
                user_id=sender.id,
                username=sender.username,
                text=text,
                message_id=event.message.id,
            )
    
    async def run_until_disconnected(self) -> None:
        """Run client until disconnected."""
        if self._client:
            await self._client.run_until_disconnected()
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()

    # =========================================
    # Channel/Chat Scraping
    # =========================================

    async def join_channel(self, channel_link: str) -> Optional[Channel | Chat]:
        """
        Join a channel or chat by link.

        Args:
            channel_link: t.me link or @username

        Returns:
            Channel/Chat entity if joined successfully, None otherwise
        """
        if not self._client:
            return None

        try:
            # Check if it's a private invite link (t.me/+hash or t.me/joinchat/hash)
            invite_hash = self._extract_invite_hash(channel_link)

            if invite_hash:
                # Join via invite link
                try:
                    result = await self._client(ImportChatInviteRequest(invite_hash))
                    logger.info(
                        "Joined private channel via invite",
                        account_id=self._account_id,
                        channel=channel_link,
                    )
                    # ImportChatInviteRequest returns Updates with chats
                    if hasattr(result, 'chats') and result.chats:
                        return result.chats[0]
                    return None
                except Exception as e:
                    # Maybe already a member - try to get from dialogs
                    if "already" in str(e).lower():
                        logger.info("Already a member of channel", channel=channel_link)
                        # Search in dialogs to get entity
                        return await self._find_channel_in_dialogs(channel_link)
                    raise

            # Public channel - join by username
            username = self._parse_channel_link(channel_link)
            if not username:
                logger.warning("Invalid channel link", link=channel_link)
                return None

            entity = await self._client.get_entity(username)
            if isinstance(entity, (Channel, Chat)):
                try:
                    await self._client(JoinChannelRequest(entity))
                except Exception as e:
                    # Might already be a member
                    if "already" not in str(e).lower():
                        raise
                logger.info(
                    "Joined channel",
                    account_id=self._account_id,
                    channel=username,
                )
                return entity

            return None

        except FloodWaitError as e:
            logger.warning("Flood wait on join", seconds=e.seconds)
            raise TelegramFloodError(e.seconds)
        except Exception as e:
            logger.error(
                "Failed to join channel",
                channel=channel_link,
                error=str(e),
            )
            return None

    async def _find_channel_in_dialogs(self, channel_link: str) -> Optional[Channel | Chat]:
        """Find a channel in dialogs by matching link or recent join."""
        if not self._client:
            return None

        try:
            # Get invite hash for matching
            invite_hash = self._extract_invite_hash(channel_link)
            username = self._parse_channel_link(channel_link) if not invite_hash else None

            async for dialog in self._client.iter_dialogs(limit=50):
                entity = dialog.entity
                if isinstance(entity, (Channel, Chat)):
                    # Match by username for public channels
                    if username and hasattr(entity, 'username') and entity.username:
                        if entity.username.lower() == username.lower():
                            return entity
                    # For private channels, return recent ones (heuristic)
                    if invite_hash:
                        return entity
        except Exception as e:
            logger.debug("Error searching dialogs", error=str(e))

        return None

    def _extract_invite_hash(self, link: str) -> Optional[str]:
        """
        Extract invite hash from private channel link.

        Handles:
        - t.me/+hash
        - t.me/joinchat/hash
        - https://t.me/+hash

        Returns:
            Invite hash or None if not a private link
        """
        link = link.strip()

        # t.me/+hash format
        if "+hash" in link or "/+" in link:
            # Remove protocol
            link = link.replace("https://", "").replace("http://", "")
            if "/+" in link:
                parts = link.split("/+")
                if len(parts) > 1:
                    return parts[1].split("/")[0].split("?")[0]

        # t.me/joinchat/hash format
        if "joinchat/" in link:
            parts = link.split("joinchat/")
            if len(parts) > 1:
                return parts[1].split("/")[0].split("?")[0]

        return None

    async def leave_channel(self, channel_link: str) -> bool:
        """
        Leave a channel or chat.

        Args:
            channel_link: t.me link or @username

        Returns:
            True if left successfully
        """
        if not self._client:
            return False

        try:
            username = self._parse_channel_link(channel_link)
            if not username:
                return False

            entity = await self._client.get_entity(username)
            if isinstance(entity, (Channel, Chat)):
                await self._client(LeaveChannelRequest(entity))
                logger.info(
                    "Left channel",
                    account_id=self._account_id,
                    channel=username,
                )
                return True

            return False

        except Exception as e:
            logger.warning("Failed to leave channel", error=str(e))
            return False

    async def scrape_channel_users(
        self,
        channel_link: str,
        max_users: int = 1000,
        scrape_comments: bool = True,
        skip_bots: bool = True,
        skip_no_username: bool = True,
    ) -> list[dict]:
        """
        Scrape users from a channel/chat by link.

        For better reliability with private channels, use join_channel() first
        and then scrape_channel_users_from_entity().
        """
        entity = await self._get_channel_entity(channel_link)
        if not entity:
            logger.warning("Could not get channel entity", link=channel_link)
            return []

        return await self.scrape_channel_users_from_entity(
            entity=entity,
            max_users=max_users,
            scrape_comments=scrape_comments,
            skip_bots=skip_bots,
            skip_no_username=skip_no_username,
        )

    async def scrape_channel_users_from_entity(
        self,
        entity,
        max_users: int = 1000,
        scrape_comments: bool = True,
        skip_bots: bool = True,
        skip_no_username: bool = True,
    ) -> list[dict]:
        """
        Scrape users from a channel/chat entity.

        Collects users who posted messages or comments.

        Args:
            entity: Channel/Chat entity (from join_channel or get_entity)
            max_users: Maximum users to collect
            scrape_comments: Also scrape comment authors
            skip_bots: Skip bot accounts
            skip_no_username: Skip users without username

        Returns:
            List of user dicts with id, username, first_name, last_name
        """
        if not self._client:
            return []

        users: dict[int, dict] = {}

        try:
            # Get messages from channel
            async for message in self._client.iter_messages(entity, limit=500):
                if len(users) >= max_users:
                    break

                # Get message author
                if message.sender_id and message.sender_id not in users:
                    user_info = await self._get_user_safe(message.sender_id)
                    if user_info and self._should_include_user(
                        user_info, skip_bots, skip_no_username
                    ):
                        users[message.sender_id] = user_info

                # Get comment authors if enabled and channel has comments
                if scrape_comments and message.replies and message.replies.replies > 0:
                    try:
                        async for reply in self._client.iter_messages(
                            entity,
                            reply_to=message.id,
                            limit=100,
                        ):
                            if len(users) >= max_users:
                                break

                            if reply.sender_id and reply.sender_id not in users:
                                user_info = await self._get_user_safe(reply.sender_id)
                                if user_info and self._should_include_user(
                                    user_info, skip_bots, skip_no_username
                                ):
                                    users[reply.sender_id] = user_info

                    except Exception as e:
                        logger.debug("Error fetching replies", error=str(e))
                        continue

                # Small delay to avoid flood
                await asyncio.sleep(0.1)

            # Get channel name for logging
            channel_name = getattr(entity, 'title', None) or getattr(entity, 'username', str(entity))

            logger.info(
                "Scraped users from channel",
                account_id=self._account_id,
                channel=channel_name,
                users_count=len(users),
            )

            return list(users.values())

        except FloodWaitError as e:
            logger.warning("Flood wait on scrape", seconds=e.seconds)
            raise TelegramFloodError(e.seconds)
        except Exception as e:
            logger.error(
                "Failed to scrape channel",
                error=str(e),
            )
            return list(users.values())

    async def scrape_group_participants(
        self,
        entity,
        max_users: int = 1000,
        skip_bots: bool = True,
        skip_no_username: bool = True,
    ) -> list[dict]:
        """
        Scrape participants directly from a group/supergroup.

        Uses GetParticipants API which is more efficient for groups
        and can get all members, not just those who posted.

        Args:
            entity: Group/Channel entity
            max_users: Maximum users to collect
            skip_bots: Skip bot accounts
            skip_no_username: Skip users without username

        Returns:
            List of user dicts with id, username, first_name, last_name
        """
        if not self._client:
            return []

        users: dict[int, dict] = {}

        try:
            # Try to get participants directly (works for groups/supergroups)
            offset = 0
            limit = 100  # Telegram allows max 200 per request

            while len(users) < max_users:
                try:
                    participants = await self._client(GetParticipantsRequest(
                        channel=entity,
                        filter=ChannelParticipantsRecent(),
                        offset=offset,
                        limit=limit,
                        hash=0,
                    ))

                    if not participants.users:
                        break

                    for user in participants.users:
                        if len(users) >= max_users:
                            break

                        if isinstance(user, User):
                            user_info = {
                                "id": user.id,
                                "username": user.username,
                                "first_name": user.first_name or "",
                                "last_name": user.last_name or "",
                                "is_bot": user.bot or False,
                            }

                            if self._should_include_user(user_info, skip_bots, skip_no_username):
                                users[user.id] = user_info

                    # Check if we got all
                    if len(participants.users) < limit:
                        break

                    offset += len(participants.users)
                    await asyncio.sleep(0.5)  # Rate limiting

                except Exception as e:
                    # GetParticipants might fail for channels (broadcast channels)
                    # In that case, fall back to scraping messages
                    logger.debug("GetParticipants failed, will use message scraping", error=str(e))
                    break

            channel_name = getattr(entity, 'title', None) or getattr(entity, 'username', str(entity))

            logger.info(
                "Scraped participants from group",
                account_id=self._account_id,
                channel=channel_name,
                users_count=len(users),
            )

            return list(users.values())

        except FloodWaitError as e:
            logger.warning("Flood wait on get participants", seconds=e.seconds)
            raise TelegramFloodError(e.seconds)
        except Exception as e:
            logger.error(
                "Failed to get participants",
                error=str(e),
            )
            return list(users.values())

    async def _get_channel_entity(self, channel_link: str):
        """
        Get channel entity, handling both public and private channels.

        For private channels, searches through dialogs after joining.
        """
        if not self._client:
            return None

        # First try public channel by username
        invite_hash = self._extract_invite_hash(channel_link)

        if not invite_hash:
            # Public channel
            username = self._parse_channel_link(channel_link)
            if username:
                try:
                    return await self._client.get_entity(username)
                except Exception as e:
                    logger.debug("Could not get entity by username", error=str(e))

        # For private channels or if public failed, search in dialogs
        # The channel should be in dialogs after joining
        try:
            async for dialog in self._client.iter_dialogs():
                entity = dialog.entity
                if isinstance(entity, (Channel, Chat)):
                    # Check if it matches by invite link or title
                    if invite_hash and hasattr(entity, 'username'):
                        # Already found, return it
                        pass
                    # For recently joined channels, they should be near the top
                    # Return first channel/chat we find in recent dialogs
                    # This is a heuristic - ideally we'd match by ID stored during join
                    return entity
        except Exception as e:
            logger.debug("Could not search dialogs", error=str(e))

        return None

    async def _get_user_safe(self, user_id: int) -> Optional[dict]:
        """Get user info safely, returns None on error."""
        try:
            entity = await self._client.get_entity(user_id)
            if isinstance(entity, User):
                return {
                    "id": entity.id,
                    "username": entity.username,
                    "first_name": entity.first_name or "",
                    "last_name": entity.last_name or "",
                    "is_bot": entity.bot or False,
                }
        except Exception:
            pass
        return None

    def _should_include_user(
        self,
        user_info: dict,
        skip_bots: bool,
        skip_no_username: bool,
    ) -> bool:
        """Check if user should be included in results."""
        if skip_bots and user_info.get("is_bot"):
            return False
        if skip_no_username and not user_info.get("username"):
            return False
        return True

    def _parse_channel_link(self, link: str) -> Optional[str]:
        """
        Parse channel link to username.

        Handles:
        - @username
        - t.me/username
        - https://t.me/username
        - t.me/+invite_hash (returns as-is for private channels)

        Returns:
            Username or None if invalid
        """
        link = link.strip()

        # Already a username
        if link.startswith("@"):
            return link[1:]

        # t.me link
        if "t.me/" in link:
            # Remove protocol
            link = link.replace("https://", "").replace("http://", "")
            # Get part after t.me/
            parts = link.split("t.me/")
            if len(parts) > 1:
                username = parts[1].split("/")[0].split("?")[0]
                if username.startswith("+"):
                    # Private invite link - return full link
                    return f"https://t.me/{username}"
                return username

        # Plain username
        if link and not "/" in link:
            return link

        return None


async def create_new_session(
    phone: str,
    api_id: int,
    api_hash: str,
    proxy_config: Optional[dict] = None,
) -> TelegramClient:
    """
    Create new Telegram session (for authorization).
    
    Args:
        phone: Phone number
        api_id: Telegram API ID
        api_hash: Telegram API hash
        proxy_config: Optional proxy configuration
        
    Returns:
        Connected but not authorized client
    """
    import tempfile
    import os
    
    temp_dir = tempfile.mkdtemp()
    session_path = os.path.join(temp_dir, "new_session")
    
    client = TelegramClient(
        session_path,
        api_id=api_id,
        api_hash=api_hash,
        proxy=proxy_config,
    )
    
    await client.connect()
    
    return client
