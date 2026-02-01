"""
Account authentication service.

Handles Telegram account authentication flow including:
- Phone number verification
- SMS/App code verification
- Two-factor authentication (2FA/password)
- Session management

FIXED:
- Added SessionPasswordNeededError handling for 2FA
- Proper temp file cleanup
- Better error handling
"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from uuid import UUID

import structlog
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    PasswordHashInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession
from telethon.tl.types import User, MessageEntitySpoiler
import python_socks

from src.config import get_settings
from src.domain.entities import Account, Proxy
from src.domain.exceptions import ProxyRequiredError
from src.utils.crypto import get_session_encryption
from src.infrastructure.telegram.device_fingerprint import (
    generate_random_fingerprint,
    generate_fingerprint_for_account,
)

logger = structlog.get_logger(__name__)


class AuthState(str, Enum):
    """Authentication flow states."""
    
    INITIAL = "initial"
    AWAITING_CODE = "awaiting_code"
    AWAITING_2FA = "awaiting_2fa"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AuthSession:
    """
    Represents an ongoing authentication session.

    Stores all data needed to complete the auth flow.
    """

    phone: str
    state: AuthState = AuthState.INITIAL
    phone_code_hash: Optional[str] = None
    temp_dir: Optional[str] = None
    session_path: Optional[str] = None
    proxy_id: Optional[UUID] = None
    proxy_config: Optional[dict] = None
    error_message: Optional[str] = None
    telegram_id: Optional[int] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    # Device fingerprint for unique device identity
    device_model: Optional[str] = None
    system_version: Optional[str] = None
    app_version: Optional[str] = None
    lang_code: Optional[str] = None
    system_lang_code: Optional[str] = None
    
    def cleanup(self) -> None:
        """Clean up temporary files."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                logger.warning(
                    "Failed to cleanup temp dir",
                    dir=self.temp_dir,
                    error=str(e),
                )
            self.temp_dir = None
            self.session_path = None


class AccountAuthService:
    """
    Service for authenticating Telegram accounts.
    
    Handles the multi-step authentication flow:
    1. Send code to phone
    2. Verify code
    3. Handle 2FA if enabled
    4. Save encrypted session
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
            raise ProxyRequiredError(context="proxy is required for auth operations")

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
    
    async def start_auth(
        self,
        phone: str,
        proxy: Proxy,
    ) -> AuthSession:
        """
        Start authentication flow.

        Sends verification code to the phone number.

        Args:
            phone: Phone number in international format
            proxy: Proxy to use (REQUIRED for security)

        Returns:
            AuthSession with state AWAITING_CODE

        Raises:
            ProxyRequiredError: Proxy is required
            PhoneNumberInvalidError: Invalid phone format
            PhoneNumberBannedError: Phone is banned
            FloodWaitError: Too many attempts
        """
        if proxy is None:
            raise ProxyRequiredError(context="proxy is required for authentication")
        # Create temp directory for session
        temp_dir = tempfile.mkdtemp()
        session_path = os.path.join(temp_dir, "auth_session")

        # Generate unique device fingerprint for this account
        fingerprint = generate_random_fingerprint(prefer_android=True, lang_code="ru")

        auth_session = AuthSession(
            phone=phone,
            state=AuthState.INITIAL,
            temp_dir=temp_dir,
            session_path=session_path,
            proxy_id=proxy.id if proxy else None,
            proxy_config=self._build_proxy_config(proxy),
            device_model=fingerprint.device_model,
            system_version=fingerprint.system_version,
            app_version=fingerprint.app_version,
            lang_code=fingerprint.lang_code,
            system_lang_code=fingerprint.system_lang_code,
        )

        try:
            client = TelegramClient(
                session_path,
                api_id=self._settings.telegram.api_id,
                api_hash=self._settings.telegram.api_hash.get_secret_value(),
                proxy=auth_session.proxy_config,
                device_model=fingerprint.device_model,
                system_version=fingerprint.system_version,
                app_version=fingerprint.app_version,
                lang_code=fingerprint.lang_code,
                system_lang_code=fingerprint.system_lang_code,
            )
            
            await client.connect()
            
            # Send code request
            sent = await client.send_code_request(phone)
            
            auth_session.phone_code_hash = sent.phone_code_hash
            auth_session.state = AuthState.AWAITING_CODE
            
            await client.disconnect()
            
            logger.info(
                "Auth code sent",
                phone=phone[:4] + "****",
            )
            
            return auth_session
            
        except PhoneNumberInvalidError:
            auth_session.state = AuthState.FAILED
            auth_session.error_message = "Неверный формат номера телефона"
            auth_session.cleanup()
            raise
            
        except PhoneNumberBannedError:
            auth_session.state = AuthState.FAILED
            auth_session.error_message = "Номер заблокирован в Telegram"
            auth_session.cleanup()
            raise
            
        except FloodWaitError as e:
            auth_session.state = AuthState.FAILED
            auth_session.error_message = f"Слишком много попыток. Подождите {e.seconds} сек."
            auth_session.cleanup()
            raise
            
        except Exception as e:
            auth_session.state = AuthState.FAILED
            auth_session.error_message = str(e)
            auth_session.cleanup()
            logger.error("Auth start failed", error=str(e))
            raise
    
    async def verify_code(
        self,
        auth_session: AuthSession,
        code: str,
    ) -> AuthSession:
        """
        Verify the authentication code.
        
        Args:
            auth_session: Current auth session
            code: Verification code from Telegram
            
        Returns:
            AuthSession with state COMPLETED or AWAITING_2FA
            
        Raises:
            PhoneCodeInvalidError: Wrong code
            PhoneCodeExpiredError: Code expired
            SessionPasswordNeededError: 2FA required
        """
        if auth_session.state != AuthState.AWAITING_CODE:
            raise ValueError("Invalid auth state for code verification")
        
        try:
            client = TelegramClient(
                auth_session.session_path,
                api_id=self._settings.telegram.api_id,
                api_hash=self._settings.telegram.api_hash.get_secret_value(),
                proxy=auth_session.proxy_config,
                device_model=auth_session.device_model,
                system_version=auth_session.system_version,
                app_version=auth_session.app_version,
                lang_code=auth_session.lang_code,
                system_lang_code=auth_session.system_lang_code,
            )

            await client.connect()

            # Try to sign in with code
            try:
                await client.sign_in(
                    phone=auth_session.phone,
                    code=code,
                    phone_code_hash=auth_session.phone_code_hash,
                )
                
                # Success - get user info
                me = await client.get_me()
                auth_session.telegram_id = me.id
                auth_session.username = me.username
                auth_session.first_name = me.first_name or ""
                auth_session.last_name = me.last_name or ""
                auth_session.state = AuthState.COMPLETED
                
            except SessionPasswordNeededError:
                # 2FA is enabled
                auth_session.state = AuthState.AWAITING_2FA
                logger.info(
                    "2FA required",
                    phone=auth_session.phone[:4] + "****",
                )
            
            await client.disconnect()
            return auth_session
            
        except PhoneCodeInvalidError:
            auth_session.error_message = "Неверный код"
            raise
            
        except PhoneCodeExpiredError:
            auth_session.state = AuthState.FAILED
            auth_session.error_message = "Код истёк. Начните заново."
            auth_session.cleanup()
            raise
            
        except Exception as e:
            auth_session.error_message = str(e)
            logger.error("Code verification failed", error=str(e))
            raise
    
    async def verify_2fa(
        self,
        auth_session: AuthSession,
        password: str,
    ) -> AuthSession:
        """
        Verify two-factor authentication password.
        
        Args:
            auth_session: Current auth session in AWAITING_2FA state
            password: 2FA password
            
        Returns:
            AuthSession with state COMPLETED
            
        Raises:
            PasswordHashInvalidError: Wrong password
        """
        if auth_session.state != AuthState.AWAITING_2FA:
            raise ValueError("Invalid auth state for 2FA verification")
        
        try:
            client = TelegramClient(
                auth_session.session_path,
                api_id=self._settings.telegram.api_id,
                api_hash=self._settings.telegram.api_hash.get_secret_value(),
                proxy=auth_session.proxy_config,
                device_model=auth_session.device_model,
                system_version=auth_session.system_version,
                app_version=auth_session.app_version,
                lang_code=auth_session.lang_code,
                system_lang_code=auth_session.system_lang_code,
            )

            await client.connect()

            # Sign in with password
            await client.sign_in(password=password)
            
            # Success - get user info
            me = await client.get_me()
            auth_session.telegram_id = me.id
            auth_session.username = me.username
            auth_session.first_name = me.first_name or ""
            auth_session.last_name = me.last_name or ""
            auth_session.state = AuthState.COMPLETED
            
            await client.disconnect()
            
            logger.info(
                "2FA verified",
                phone=auth_session.phone[:4] + "****",
            )
            
            return auth_session
            
        except PasswordHashInvalidError:
            auth_session.error_message = "Неверный пароль 2FA"
            raise
            
        except Exception as e:
            auth_session.error_message = str(e)
            logger.error("2FA verification failed", error=str(e))
            raise
    
    async def get_encrypted_session(
        self,
        auth_session: AuthSession,
    ) -> bytes:
        """
        Get encrypted session data from completed auth.
        
        Args:
            auth_session: Completed auth session
            
        Returns:
            Encrypted session bytes
        """
        if auth_session.state != AuthState.COMPLETED:
            raise ValueError("Auth not completed")
        
        # Read session file
        session_file = auth_session.session_path + ".session"
        
        if not os.path.exists(session_file):
            raise FileNotFoundError("Session file not found")
        
        with open(session_file, "rb") as f:
            session_bytes = f.read()
        
        # Encrypt session data
        encrypted = self._encryption.encrypt(session_bytes)
        
        return encrypted
    
    def finalize(self, auth_session: AuthSession) -> None:
        """
        Finalize authentication and cleanup.

        Should be called after session data is saved to DB.
        """
        auth_session.cleanup()

    async def auto_reauthorize(
        self,
        old_session_data: bytes,
        phone: str,
        proxy: Proxy,
        twofa_password: Optional[str] = None,
        timeout_seconds: int = 120,
        progress_callback: Optional[callable] = None,
    ) -> tuple[bytes, dict]:
        """
        Automatically re-authorize account by intercepting login code.

        This method:
        1. Connects to the existing session
        2. Creates a new session and requests login code
        3. Waits for the code to arrive in the old session
        4. Uses the code to complete authorization in new session
        5. Returns the new encrypted session

        Args:
            old_session_data: Encrypted session data of existing account
            phone: Phone number in international format
            proxy: Proxy to use (REQUIRED for security)
            twofa_password: 2FA password if account has it enabled
            timeout_seconds: How long to wait for the code
            progress_callback: Optional async callback for progress updates

        Returns:
            Tuple of (encrypted_session_bytes, user_info_dict)

        Raises:
            ProxyRequiredError: Proxy is required
            Exception: Various auth errors
        """
        if proxy is None:
            raise ProxyRequiredError(context="proxy is required for re-authorization")
        import asyncio
        import datetime
        import re

        # Decrypt old session
        decrypted = self._encryption.decrypt(old_session_data)
        try:
            old_session_string = decrypted.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError("Cannot decode old session data")

        proxy_config = self._build_proxy_config(proxy)

        # Generate new fingerprint for new session
        new_fingerprint = generate_random_fingerprint(prefer_android=True, lang_code="ru")

        # Create clients
        old_client = None
        new_client = None

        try:
            # Connect to old session (use same fingerprint as it was created with)
            old_client = TelegramClient(
                StringSession(old_session_string),
                api_id=self._settings.telegram.api_id,
                api_hash=self._settings.telegram.api_hash.get_secret_value(),
                proxy=proxy_config,
            )

            await old_client.connect()

            if not await old_client.is_user_authorized():
                raise ValueError("Old session is not authorized")

            if progress_callback:
                await progress_callback("connected_old", "Подключен к старой сессии")

            # Create new client with StringSession and NEW fingerprint
            # StringSession allows us to get session string via .save()
            new_client = TelegramClient(
                StringSession(),
                api_id=self._settings.telegram.api_id,
                api_hash=self._settings.telegram.api_hash.get_secret_value(),
                proxy=proxy_config,
                device_model=new_fingerprint.device_model,
                system_version=new_fingerprint.system_version,
                app_version=new_fingerprint.app_version,
                lang_code=new_fingerprint.lang_code,
                system_lang_code=new_fingerprint.system_lang_code,
            )

            await new_client.connect()

            if progress_callback:
                await progress_callback("requesting_code", "Запрашиваю код авторизации...")

            sent = await new_client.send_code_request(phone)
            phone_code_hash = sent.phone_code_hash

            if progress_callback:
                await progress_callback("waiting_code", "Ожидаю код в старой сессии...")

            # Wait for code in old session
            TELEGRAM_SERVICE_ID = 777000
            code_found = None
            start_time = asyncio.get_event_loop().time()

            while not code_found:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout_seconds:
                    break

                # Update progress
                remaining = int(timeout_seconds - elapsed)
                if progress_callback and remaining % 10 == 0:
                    await progress_callback("waiting", f"Ожидаю код... ({remaining} сек)")

                # Force fetch updates
                try:
                    await old_client.catch_up()
                except Exception:
                    pass

                # Check for messages from Telegram
                try:
                    async for dialog in old_client.iter_dialogs(limit=15):
                        entity = dialog.entity
                        if isinstance(entity, User) and entity.id == TELEGRAM_SERVICE_ID:
                            async for msg in old_client.iter_messages(entity, limit=5):
                                if msg.date:
                                    age = (datetime.datetime.now(datetime.timezone.utc) - msg.date).total_seconds()
                                    if age < 180:
                                        code = self._extract_code_from_message(msg)
                                        if code:
                                            code_found = code
                                            break
                            break
                except Exception:
                    pass

                # Also try direct access
                if not code_found:
                    try:
                        async for msg in old_client.iter_messages(TELEGRAM_SERVICE_ID, limit=5):
                            if msg.date:
                                age = (datetime.datetime.now(datetime.timezone.utc) - msg.date).total_seconds()
                                if age < 180:
                                    code = self._extract_code_from_message(msg)
                                    if code:
                                        code_found = code
                                        break
                    except Exception:
                        pass

                if not code_found:
                    await asyncio.sleep(2)

            if not code_found:
                raise TimeoutError("Таймаут ожидания кода авторизации")

            if progress_callback:
                await progress_callback("code_received", f"Код получен: {code_found}")

            # Use code to authorize new session
            try:
                await new_client.sign_in(
                    phone=phone,
                    code=code_found,
                    phone_code_hash=phone_code_hash,
                )
            except SessionPasswordNeededError:
                if not twofa_password:
                    raise ValueError("Требуется пароль 2FA")
                await new_client.sign_in(password=twofa_password)

            # Get user info
            me = await new_client.get_me()
            user_info = {
                "telegram_id": me.id,
                "username": me.username,
                "first_name": me.first_name or "",
                "last_name": me.last_name or "",
                "is_premium": getattr(me, "premium", False),
                "device_model": new_fingerprint.device_model,
                "system_version": new_fingerprint.system_version,
                "app_version": new_fingerprint.app_version,
            }

            if progress_callback:
                await progress_callback("authorized", "Авторизация успешна!")

            # Get new session string
            new_session_string = new_client.session.save()

            # Disconnect clients
            await new_client.disconnect()
            await old_client.disconnect()

            # Encrypt new session
            encrypted = self._encryption.encrypt(new_session_string.encode('utf-8'))

            logger.info(
                "Auto-reauthorization successful",
                phone=phone[:4] + "****",
                telegram_id=me.id,
                device=new_fingerprint.device_model,
            )

            return encrypted, user_info

        finally:
            # Cleanup
            if old_client:
                try:
                    await old_client.disconnect()
                except Exception:
                    pass
            if new_client:
                try:
                    await new_client.disconnect()
                except Exception:
                    pass

    def _extract_code_from_message(self, msg) -> Optional[str]:
        """Extract login code from Telegram message."""
        import re

        if not msg:
            return None

        text = msg.text or msg.raw_text or ""

        # First, try to extract code from spoiler entities
        if msg.entities:
            for entity in msg.entities:
                if isinstance(entity, MessageEntitySpoiler):
                    spoiler_text = text[entity.offset:entity.offset + entity.length]
                    clean = spoiler_text.replace('-', '').replace(' ', '').strip()
                    if clean.isdigit() and 5 <= len(clean) <= 6:
                        return clean

        # Fallback: search in full text
        patterns = [
            r'(?:login\s*code|код входа|код|code)[:\s]+(\d{5,6})',
            r'(\d{5,6})\s*[-–—]\s*(?:это|is)',
            r'(\d{3}[-\s]?\d{3})',
            r'(?:^|\s)(\d{5,6})(?:\s|$|\.)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                code = match.group(1).replace('-', '').replace(' ', '')
                if 5 <= len(code) <= 6:
                    return code

        return None


# Singleton instance
_auth_service: Optional[AccountAuthService] = None


def get_auth_service() -> AccountAuthService:
    """Get account auth service singleton."""
    global _auth_service
    
    if _auth_service is None:
        _auth_service = AccountAuthService()
    
    return _auth_service
