"""
Account profile customization service.

Handles updating Telegram profile:
- First/Last name
- Bio (about)
- Profile photo
"""

import os
import tempfile
from typing import Optional
from uuid import UUID

import structlog
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.types import InputPhoto
import python_socks

from src.config import get_settings
from src.domain.entities import Proxy
from src.domain.exceptions import ProxyRequiredError
from src.utils.crypto import get_session_encryption

logger = structlog.get_logger(__name__)


class AccountProfileService:
    """
    Service for customizing Telegram account profiles.

    Allows updating:
    - First name and last name
    - Bio/About section
    - Profile photo
    """

    def __init__(self):
        self._settings = get_settings()
        self._encryption = get_session_encryption()

    def _build_proxy_config(self, proxy: Proxy) -> dict:
        """Build Telethon proxy configuration.

        Args:
            proxy: Proxy entity (required)

        Returns:
            Proxy config dict for Telethon client.

        Raises:
            ProxyRequiredError: If proxy is None.
        """
        if proxy is None:
            raise ProxyRequiredError(context="proxy is required for profile operations")

        proxy_type_map = {
            "socks5": python_socks.ProxyType.SOCKS5,
            "socks4": python_socks.ProxyType.SOCKS4,
            "http": python_socks.ProxyType.HTTP,
            "https": python_socks.ProxyType.HTTP,
        }

        return {
            "proxy_type": proxy_type_map.get(
                proxy.proxy_type.value,
                python_socks.ProxyType.SOCKS5,
            ),
            "addr": proxy.host,
            "port": proxy.port,
            "username": proxy.username,
            "password": proxy.password,
            "rdns": True,
        }

    async def update_profile(
        self,
        session_data: bytes,
        proxy: Proxy,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        bio: Optional[str] = None,
    ) -> dict:
        """
        Update account profile (name and bio).

        Args:
            session_data: Encrypted session data
            proxy: Proxy to use (REQUIRED for security)
            first_name: New first name (None to keep current)
            last_name: New last name (None to keep current, "" to clear)
            bio: New bio (None to keep current, "" to clear)

        Returns:
            Dict with updated profile info

        Raises:
            ProxyRequiredError: Proxy is required
        """
        if proxy is None:
            raise ProxyRequiredError(context="proxy is required for profile update")
        # Decrypt session
        decrypted = self._encryption.decrypt(session_data)
        try:
            session_string = decrypted.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError("Cannot decode session data")

        proxy_config = self._build_proxy_config(proxy)

        client = TelegramClient(
            StringSession(session_string),
            api_id=self._settings.telegram.api_id,
            api_hash=self._settings.telegram.api_hash.get_secret_value(),
            proxy=proxy_config,
        )

        try:
            await client.connect()

            if not await client.is_user_authorized():
                raise ValueError("Session is not authorized")

            # Get current profile
            me = await client.get_me()

            # Build update request
            update_first = first_name if first_name is not None else me.first_name
            update_last = last_name if last_name is not None else (me.last_name or "")
            update_bio = bio  # None means don't update

            # Update profile
            await client(UpdateProfileRequest(
                first_name=update_first,
                last_name=update_last,
                about=update_bio if update_bio is not None else None,
            ))

            # Get updated profile
            me = await client.get_me()

            logger.info(
                "Profile updated",
                telegram_id=me.id,
                first_name=me.first_name,
            )

            return {
                "telegram_id": me.id,
                "first_name": me.first_name,
                "last_name": me.last_name or "",
                "username": me.username,
                "bio": update_bio if update_bio is not None else None,
            }

        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def update_photo(
        self,
        session_data: bytes,
        photo_bytes: bytes,
        proxy: Proxy,
    ) -> dict:
        """
        Update account profile photo.

        Args:
            session_data: Encrypted session data
            photo_bytes: Photo file bytes (JPEG/PNG)
            proxy: Proxy to use (REQUIRED for security)

        Returns:
            Dict with success status

        Raises:
            ProxyRequiredError: Proxy is required
        """
        if proxy is None:
            raise ProxyRequiredError(context="proxy is required for photo update")
        # Decrypt session
        decrypted = self._encryption.decrypt(session_data)
        try:
            session_string = decrypted.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError("Cannot decode session data")

        proxy_config = self._build_proxy_config(proxy)

        client = TelegramClient(
            StringSession(session_string),
            api_id=self._settings.telegram.api_id,
            api_hash=self._settings.telegram.api_hash.get_secret_value(),
            proxy=proxy_config,
        )

        try:
            await client.connect()

            if not await client.is_user_authorized():
                raise ValueError("Session is not authorized")

            # Save photo to temp file
            temp_dir = tempfile.mkdtemp()
            temp_path = os.path.join(temp_dir, "photo.jpg")

            try:
                with open(temp_path, 'wb') as f:
                    f.write(photo_bytes)

                # Upload photo
                result = await client(UploadProfilePhotoRequest(
                    file=await client.upload_file(temp_path),
                ))

                logger.info("Profile photo updated")

                return {
                    "success": True,
                    "photo_id": result.photo.id if hasattr(result, 'photo') else None,
                }

            finally:
                # Cleanup temp file
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)

        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def delete_photos(
        self,
        session_data: bytes,
        proxy: Proxy,
    ) -> dict:
        """
        Delete all profile photos.

        Args:
            session_data: Encrypted session data
            proxy: Proxy to use (REQUIRED for security)

        Returns:
            Dict with success status

        Raises:
            ProxyRequiredError: Proxy is required
        """
        if proxy is None:
            raise ProxyRequiredError(context="proxy is required for photo deletion")
        # Decrypt session
        decrypted = self._encryption.decrypt(session_data)
        try:
            session_string = decrypted.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError("Cannot decode session data")

        proxy_config = self._build_proxy_config(proxy)

        client = TelegramClient(
            StringSession(session_string),
            api_id=self._settings.telegram.api_id,
            api_hash=self._settings.telegram.api_hash.get_secret_value(),
            proxy=proxy_config,
        )

        try:
            await client.connect()

            if not await client.is_user_authorized():
                raise ValueError("Session is not authorized")

            # Get current photos
            photos = await client.get_profile_photos('me')

            if photos:
                # Delete all photos
                input_photos = [
                    InputPhoto(
                        id=photo.id,
                        access_hash=photo.access_hash,
                        file_reference=photo.file_reference,
                    )
                    for photo in photos
                ]
                await client(DeletePhotosRequest(id=input_photos))

            logger.info("Profile photos deleted", count=len(photos) if photos else 0)

            return {
                "success": True,
                "deleted_count": len(photos) if photos else 0,
            }

        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


# Singleton instance
_profile_service: Optional[AccountProfileService] = None


def get_profile_service() -> AccountProfileService:
    """Get account profile service singleton."""
    global _profile_service

    if _profile_service is None:
        _profile_service = AccountProfileService()

    return _profile_service
