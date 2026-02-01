"""Telegram client for comment bot."""

import asyncio
import io
import tempfile
from pathlib import Path
from typing import Optional, Union

import structlog
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
)
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel, InputPhoto

from src.commentbot.config import get_config, get_session_encryption

logger = structlog.get_logger(__name__)


class CommentBotClient:
    """
    Telegram client for posting comments.

    Handles:
    - Phone number authorization
    - tdata session loading
    - Posting comments to channels/chats
    """

    def __init__(
        self,
        account_id: str,
        session_data: Optional[bytes] = None,
        tdata_path: Optional[str] = None,
    ):
        """
        Initialize client.

        Args:
            account_id: Unique account identifier
            session_data: Encrypted session string
            tdata_path: Path to tdata folder
        """
        self._account_id = account_id
        self._session_data = session_data
        self._tdata_path = tdata_path
        self._client: Optional[TelegramClient] = None
        self._connected = False
        self._config = get_config()

    @property
    def connected(self) -> bool:
        """Check if connected."""
        return self._connected and self._client is not None

    @property
    def client(self) -> Optional[TelegramClient]:
        """Get underlying client."""
        return self._client

    async def connect(self) -> None:
        """Connect to Telegram using existing session."""
        if self._connected:
            return

        session = await self._prepare_session()

        self._client = TelegramClient(
            session,
            api_id=self._config.telegram_api_id,
            api_hash=self._config.telegram_api_hash.get_secret_value(),
        )

        await self._client.connect()

        if not await self._client.is_user_authorized():
            raise ValueError("Session not authorized")

        self._connected = True
        logger.info("Comment bot client connected", account_id=self._account_id)

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

    async def _prepare_session(self) -> Union[str, StringSession]:
        """Prepare session for connection."""
        if self._session_data:
            # Decrypt session data
            encryption = get_session_encryption()
            decrypted = encryption.decrypt(self._session_data)

            # Check if SQLite or StringSession
            if decrypted.startswith(b"SQLite format 3\x00"):
                from src.commentbot.config import COMMENTBOT_DIR
                session_dir = COMMENTBOT_DIR / "data" / "sessions"
                session_dir.mkdir(parents=True, exist_ok=True)
                session_path = session_dir / f"commentbot_{self._account_id}"
                session_file = str(session_path) + ".session"

                with open(session_file, "wb") as f:
                    f.write(decrypted)

                return str(session_path)

            # StringSession
            try:
                session_str = decrypted.decode().strip()
            except Exception:
                session_str = decrypted.decode("utf-8", errors="ignore").strip()

            return StringSession(session_str)

        if self._tdata_path:
            # TODO: Implement tdata conversion
            raise NotImplementedError("tdata auth not yet implemented")

        raise ValueError("No session data provided")

    # =========================================
    # Phone Authorization Flow
    # =========================================

    @classmethod
    async def start_phone_auth(
        cls,
        phone: str,
        api_id: int,
        api_hash: str,
    ) -> tuple[TelegramClient, str]:
        """
        Start phone authorization - send code.

        Args:
            phone: Phone number with country code
            api_id: Telegram API ID
            api_hash: Telegram API hash

        Returns:
            Tuple of (client, phone_code_hash)
        """
        client = TelegramClient(
            StringSession(),
            api_id=api_id,
            api_hash=api_hash,
        )

        await client.connect()

        result = await client.send_code_request(phone)
        phone_code_hash = result.phone_code_hash

        logger.info("Auth code sent", phone=phone[:4] + "****")

        return client, phone_code_hash

    @classmethod
    async def complete_phone_auth(
        cls,
        client: TelegramClient,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: Optional[str] = None,
    ) -> str:
        """
        Complete phone authorization with code.

        Args:
            client: Client from start_phone_auth
            phone: Phone number
            code: SMS/Telegram code
            phone_code_hash: Hash from start_phone_auth
            password: 2FA password if required

        Returns:
            Session string

        Raises:
            SessionPasswordNeededError: If 2FA is required
            PhoneCodeInvalidError: If code is wrong
            PhoneCodeExpiredError: If code expired
        """
        try:
            await client.sign_in(
                phone=phone,
                code=code,
                phone_code_hash=phone_code_hash,
            )
        except SessionPasswordNeededError:
            if not password:
                raise
            await client.sign_in(password=password)

        # Get session string
        session_string = client.session.save()

        logger.info("Phone auth completed", phone=phone[:4] + "****")

        return session_string

    @classmethod
    async def complete_2fa(
        cls,
        client: TelegramClient,
        password: str,
    ) -> str:
        """
        Complete 2FA authentication.

        Args:
            client: Client waiting for 2FA
            password: 2FA password

        Returns:
            Session string

        Raises:
            PasswordHashInvalidError: If password is wrong
        """
        await client.sign_in(password=password)
        session_string = client.session.save()

        logger.info("2FA auth completed")

        return session_string

    # =========================================
    # Comment Operations
    # =========================================

    async def post_comment(
        self,
        channel: str,
        post_id: int,
        text: str,
    ) -> Optional[int]:
        """
        Post a comment to a channel post.

        Args:
            channel: Channel username or link
            post_id: Post ID to comment on
            text: Comment text

        Returns:
            Comment message ID if successful

        Raises:
            FloodWaitError: If rate limited
        """
        if not self._client:
            raise ValueError("Client not connected")

        try:
            # Get channel entity
            entity = await self._client.get_entity(channel)

            # Send comment (reply to post)
            message = await self._client.send_message(
                entity,
                text,
                comment_to=post_id,
            )

            logger.info(
                "Comment posted",
                account_id=self._account_id,
                channel=channel,
                post_id=post_id,
                comment_id=message.id,
            )

            return message.id

        except FloodWaitError as e:
            logger.warning(
                "Flood wait on comment",
                account_id=self._account_id,
                seconds=e.seconds,
            )
            raise

        except Exception as e:
            logger.error(
                "Failed to post comment",
                account_id=self._account_id,
                channel=channel,
                error=str(e),
            )
            raise

    async def get_channel_posts(
        self,
        channel: str,
        limit: int = 10,
    ) -> list[dict]:
        """
        Get recent posts from a channel.

        Args:
            channel: Channel username or link
            limit: Max posts to fetch

        Returns:
            List of post dicts with id, text, date
        """
        if not self._client:
            raise ValueError("Client not connected")

        try:
            entity = await self._client.get_entity(channel)
            posts = []

            async for message in self._client.iter_messages(entity, limit=limit):
                posts.append({
                    "id": message.id,
                    "text": message.text or "",
                    "date": message.date,
                    "views": getattr(message, "views", 0),
                })

            return posts

        except Exception as e:
            logger.error(
                "Failed to get posts",
                account_id=self._account_id,
                channel=channel,
                error=str(e),
            )
            return []

    # =========================================
    # Profile Copy Operations
    # =========================================

    async def get_channel_info(self, channel: str) -> Optional[dict]:
        """
        Get channel information (name, about, photo).

        Args:
            channel: Channel username or link

        Returns:
            Dict with title, about, has_photo
        """
        if not self._client:
            raise ValueError("Client not connected")

        try:
            entity = await self._client.get_entity(channel)

            if not isinstance(entity, Channel):
                logger.warning("Entity is not a channel", channel=channel)
                return None

            # Get full channel info
            full = await self._client(GetFullChannelRequest(entity))

            return {
                "id": entity.id,
                "title": entity.title,
                "username": entity.username,
                "about": full.full_chat.about or "",
                "has_photo": entity.photo is not None,
                "entity": entity,
            }

        except Exception as e:
            logger.error(
                "Failed to get channel info",
                channel=channel,
                error=str(e),
            )
            return None

    async def download_channel_photo(self, channel: str) -> Optional[bytes]:
        """
        Download channel profile photo.

        Args:
            channel: Channel username or link

        Returns:
            Photo bytes or None
        """
        if not self._client:
            raise ValueError("Client not connected")

        try:
            entity = await self._client.get_entity(channel)

            if not entity.photo:
                logger.debug("Channel has no photo", channel=channel)
                return None

            # Download photo to bytes
            photo_bytes = await self._client.download_profile_photo(
                entity,
                file=bytes,
            )

            if photo_bytes:
                logger.info(
                    "Channel photo downloaded",
                    channel=channel,
                    size=len(photo_bytes),
                )

            return photo_bytes

        except Exception as e:
            logger.error(
                "Failed to download channel photo",
                channel=channel,
                error=str(e),
            )
            return None

    async def update_profile_name(
        self,
        first_name: str,
        last_name: str = "",
        about: str = "",
    ) -> bool:
        """
        Update account profile name and bio.

        Args:
            first_name: First name (required, max 64 chars)
            last_name: Last name (optional, max 64 chars)
            about: Bio/about text (optional, max 70 chars)

        Returns:
            True if successful
        """
        if not self._client:
            raise ValueError("Client not connected")

        try:
            # Telegram limits
            first_name = first_name[:64].strip()
            last_name = last_name[:64].strip() if last_name else ""
            about = about[:70].strip() if about else ""

            # Ensure first name is not empty
            if not first_name:
                first_name = "User"

            await self._client(UpdateProfileRequest(
                first_name=first_name,
                last_name=last_name,
                about=about,
            ))

            logger.info(
                "Profile name updated",
                account_id=self._account_id,
                first_name=first_name,
                last_name=last_name,
            )

            return True

        except FloodWaitError as e:
            logger.warning(
                "Flood wait on profile update",
                seconds=e.seconds,
            )
            raise

        except Exception as e:
            logger.error(
                "Failed to update profile name",
                error=str(e),
            )
            return False

    async def update_profile_photo(self, photo_bytes: bytes) -> bool:
        """
        Update account profile photo.

        Args:
            photo_bytes: Photo file bytes (JPEG/PNG)

        Returns:
            True if successful
        """
        if not self._client:
            raise ValueError("Client not connected")

        try:
            # Upload photo file
            file = await self._client.upload_file(
                io.BytesIO(photo_bytes),
                file_name="profile.jpg",
            )

            # Set as profile photo
            await self._client(UploadProfilePhotoRequest(file=file))

            logger.info(
                "Profile photo updated",
                account_id=self._account_id,
                size=len(photo_bytes),
            )

            return True

        except FloodWaitError as e:
            logger.warning(
                "Flood wait on photo update",
                seconds=e.seconds,
            )
            raise

        except Exception as e:
            logger.error(
                "Failed to update profile photo",
                error=str(e),
            )
            return False

    async def copy_channel_profile(
        self,
        channel: str,
        copy_name: bool = True,
        copy_photo: bool = True,
        copy_about: bool = False,
    ) -> dict:
        """
        Copy channel profile to account.

        Copies channel name and/or photo to the account's profile.

        Args:
            channel: Channel username or link
            copy_name: Copy channel title as first name
            copy_photo: Copy channel photo
            copy_about: Copy channel description as bio

        Returns:
            Dict with results: {name_copied, photo_copied, channel_title}
        """
        if not self._client:
            raise ValueError("Client not connected")

        result = {
            "success": False,
            "name_copied": False,
            "photo_copied": False,
            "channel_title": None,
            "error": None,
        }

        try:
            # Get channel info
            info = await self.get_channel_info(channel)
            if not info:
                result["error"] = "Could not get channel info"
                return result

            result["channel_title"] = info["title"]

            # Copy name
            if copy_name:
                # Parse channel title into first/last name
                title = info["title"]
                parts = title.split(maxsplit=1)
                first_name = parts[0] if parts else title
                last_name = parts[1] if len(parts) > 1 else ""

                about = info["about"] if copy_about else ""

                name_success = await self.update_profile_name(
                    first_name=first_name,
                    last_name=last_name,
                    about=about,
                )
                result["name_copied"] = name_success

            # Copy photo
            if copy_photo and info["has_photo"]:
                photo_bytes = await self.download_channel_photo(channel)
                if photo_bytes:
                    photo_success = await self.update_profile_photo(photo_bytes)
                    result["photo_copied"] = photo_success

            result["success"] = result["name_copied"] or result["photo_copied"]

            logger.info(
                "Channel profile copied",
                account_id=self._account_id,
                channel=channel,
                name_copied=result["name_copied"],
                photo_copied=result["photo_copied"],
            )

            return result

        except FloodWaitError as e:
            result["error"] = f"Flood wait: {e.seconds}s"
            raise

        except Exception as e:
            result["error"] = str(e)
            logger.error(
                "Failed to copy channel profile",
                channel=channel,
                error=str(e),
            )
            return result

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
