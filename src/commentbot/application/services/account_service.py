"""Account service for comment bot."""

from typing import Optional
from uuid import UUID

import structlog
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    PhoneNumberInvalidError,
)

from src.commentbot.domain.entities import Account, AccountStatus
from src.commentbot.infrastructure.database.repository import AccountRepository
from src.commentbot.infrastructure.telegram import CommentBotClient
from src.commentbot.config import get_config, get_session_encryption

logger = structlog.get_logger(__name__)

# Global storage for pending auth clients (shared across AccountService instances)
_pending_clients: dict[UUID, TelegramClient] = {}


class AccountService:
    """Service for managing comment bot accounts."""

    def __init__(self, account_repo: AccountRepository):
        self.account_repo = account_repo
        self._config = get_config()

    async def start_phone_auth(
        self,
        phone: str,
        owner_id: int,
    ) -> Account:
        """
        Start phone authorization flow.

        Args:
            phone: Phone number with country code (+7...)
            owner_id: Telegram user ID of the owner

        Returns:
            Account in AUTH_CODE status

        Raises:
            PhoneNumberInvalidError: If phone is invalid
        """
        # Normalize phone
        phone = phone.strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = "+" + phone

        # Check if account already exists
        existing = await self.account_repo.get_by_phone(phone)
        if existing and existing.status == AccountStatus.ACTIVE:
            raise ValueError(f"Account {phone} already exists and is active")

        # Start auth
        try:
            client, phone_code_hash = await CommentBotClient.start_phone_auth(
                phone=phone,
                api_id=self._config.telegram_api_id,
                api_hash=self._config.telegram_api_hash.get_secret_value(),
            )
        except PhoneNumberInvalidError:
            raise ValueError(f"Invalid phone number: {phone}")

        # Create or update account
        if existing:
            account = existing
            account.status = AccountStatus.AUTH_CODE
            account.phone_code_hash = phone_code_hash
            account.error_message = None
        else:
            account = Account(
                phone=phone,
                status=AccountStatus.AUTH_CODE,
                phone_code_hash=phone_code_hash,
                owner_id=owner_id,
            )

        await self.account_repo.save(account)

        # Store client for code verification
        _pending_clients[account.id] = client

        logger.info(
            "Phone auth started",
            account_id=str(account.id),
            phone=phone[:4] + "****",
        )

        return account

    async def verify_code(
        self,
        account_id: UUID,
        code: str,
    ) -> Account:
        """
        Verify SMS/Telegram code.

        Args:
            account_id: Account ID
            code: Verification code

        Returns:
            Updated account (ACTIVE or AUTH_2FA)

        Raises:
            PhoneCodeInvalidError: If code is wrong
            PhoneCodeExpiredError: If code expired
        """
        account = await self.account_repo.get_by_id(account_id)
        if not account:
            raise ValueError("Account not found")

        if account.status != AccountStatus.AUTH_CODE:
            raise ValueError(f"Account not in AUTH_CODE status: {account.status}")

        client = _pending_clients.get(account_id)
        if not client:
            raise ValueError("Auth session expired, start again")

        try:
            session_string = await CommentBotClient.complete_phone_auth(
                client=client,
                phone=account.phone,
                code=code,
                phone_code_hash=account.phone_code_hash,
            )

            # Encrypt and save session
            encryption = get_session_encryption()
            encrypted = encryption.encrypt(session_string.encode())

            account.mark_active(encrypted)
            await self.account_repo.save(account)

            # Cleanup
            del _pending_clients[account_id]
            await client.disconnect()

            logger.info(
                "Account authorized via code",
                account_id=str(account_id),
            )

            return account

        except SessionPasswordNeededError:
            # 2FA required
            account.status = AccountStatus.AUTH_2FA
            await self.account_repo.save(account)

            logger.info(
                "2FA required",
                account_id=str(account_id),
            )

            return account

        except PhoneCodeInvalidError:
            account.mark_error("Invalid code")
            await self.account_repo.save(account)
            raise

        except PhoneCodeExpiredError:
            account.mark_error("Code expired")
            await self.account_repo.save(account)
            # Cleanup
            if account_id in _pending_clients:
                await _pending_clients[account_id].disconnect()
                del _pending_clients[account_id]
            raise

    async def verify_2fa(
        self,
        account_id: UUID,
        password: str,
    ) -> Account:
        """
        Verify 2FA password.

        Args:
            account_id: Account ID
            password: 2FA password

        Returns:
            Updated account (ACTIVE)

        Raises:
            PasswordHashInvalidError: If password is wrong
        """
        account = await self.account_repo.get_by_id(account_id)
        if not account:
            raise ValueError("Account not found")

        if account.status != AccountStatus.AUTH_2FA:
            raise ValueError(f"Account not in AUTH_2FA status: {account.status}")

        client = _pending_clients.get(account_id)
        if not client:
            raise ValueError("Auth session expired, start again")

        try:
            session_string = await CommentBotClient.complete_2fa(
                client=client,
                password=password,
            )

            # Encrypt and save session
            encryption = get_session_encryption()
            encrypted = encryption.encrypt(session_string.encode())

            account.mark_active(encrypted)
            await self.account_repo.save(account)

            # Cleanup
            del _pending_clients[account_id]
            await client.disconnect()

            logger.info(
                "Account authorized via 2FA",
                account_id=str(account_id),
            )

            return account

        except PasswordHashInvalidError:
            account.mark_error("Invalid 2FA password")
            await self.account_repo.save(account)
            raise

    async def get_account(self, account_id: UUID) -> Optional[Account]:
        """Get account by ID."""
        return await self.account_repo.get_by_id(account_id)

    async def list_accounts(self, owner_id: int) -> list[Account]:
        """List all accounts for owner."""
        return await self.account_repo.list_by_owner(owner_id)

    async def list_active_accounts(self, owner_id: int) -> list[Account]:
        """List active accounts for owner."""
        return await self.account_repo.list_active(owner_id)

    async def delete_account(self, account_id: UUID) -> bool:
        """Delete account."""
        # Cleanup pending client if any
        if account_id in _pending_clients:
            try:
                await _pending_clients[account_id].disconnect()
            except Exception:
                pass
            del _pending_clients[account_id]

        return await self.account_repo.delete(account_id)

    async def pause_account(self, account_id: UUID) -> Optional[Account]:
        """Pause account."""
        account = await self.account_repo.get_by_id(account_id)
        if not account:
            return None

        account.pause()
        return await self.account_repo.save(account)

    async def resume_account(self, account_id: UUID) -> Optional[Account]:
        """Resume paused account."""
        account = await self.account_repo.get_by_id(account_id)
        if not account:
            return None

        account.resume()
        return await self.account_repo.save(account)

    def cleanup_pending(self) -> None:
        """Cleanup pending auth clients."""
        for client in _pending_clients.values():
            try:
                if client.is_connected():
                    client.disconnect()
            except Exception:
                pass
        _pending_clients.clear()
