"""
Premium purchase service.

Automates buying Telegram Premium through @PremiumBot.
Supports payment via Stripe tokenization.
"""

import asyncio
import re
import json
import base64
from typing import Optional
from uuid import UUID
from dataclasses import dataclass

import structlog
import httpx
from telethon import TelegramClient, functions, types
from telethon.tl.types import (
    Message,
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
    KeyboardButtonBuy,
    MessageMediaInvoice,
)

from src.infrastructure.database.repositories import PostgresAccountRepository
from src.utils.crypto import get_session_encryption
from src.config import get_settings

logger = structlog.get_logger(__name__)

PREMIUM_BOT_USERNAME = "PremiumBot"


def extract_public_token_from_url(url: str) -> Optional[str]:
    """
    Extract publicToken from Smart Glocal payment URL.

    URL format: https://payment.smart-glocal.com/.../tokenize/<base64_json>/<hash>
    The base64 part contains JSON with publicToken.
    """
    try:
        # Find base64 encoded part in URL
        # Pattern: /tokenize/<base64>/
        match = re.search(r'/tokenize/([A-Za-z0-9+/=_-]+)/', url)
        if not match:
            # Try without trailing slash
            match = re.search(r'/tokenize/([A-Za-z0-9+/=_-]+)$', url)

        if not match:
            logger.warning("Could not find base64 part in URL", url=url[:100])
            return None

        base64_part = match.group(1)

        # Fix URL-safe base64
        base64_part = base64_part.replace('-', '+').replace('_', '/')

        # Add padding if needed
        padding = 4 - len(base64_part) % 4
        if padding != 4:
            base64_part += '=' * padding

        # Decode
        decoded = base64.b64decode(base64_part)
        data = json.loads(decoded)

        public_token = data.get('publicToken')
        logger.info(
            "Extracted public token from URL",
            has_token=bool(public_token),
            data_keys=list(data.keys()),
        )

        return public_token

    except Exception as e:
        logger.error("Failed to extract public token", error=str(e), url=url[:100])
        return None


class PremiumPurchaseError(Exception):
    """Error during premium purchase."""
    pass


@dataclass
class CardData:
    """Card data for payment."""
    number: str  # Card number without spaces
    exp_month: int  # 1-12
    exp_year: int  # 4 digits (2025)
    cvc: str  # 3-4 digits

    def validate(self) -> bool:
        """Basic validation."""
        # Remove spaces from number
        number = self.number.replace(" ", "").replace("-", "")
        if not number.isdigit() or len(number) < 13 or len(number) > 19:
            return False
        if not (1 <= self.exp_month <= 12):
            return False
        if not (2024 <= self.exp_year <= 2040):
            return False
        if not self.cvc.isdigit() or len(self.cvc) < 3 or len(self.cvc) > 4:
            return False
        return True

    @property
    def clean_number(self) -> str:
        return self.number.replace(" ", "").replace("-", "")


@dataclass
class PaymentFormInfo:
    """Info about payment form."""
    form_id: int
    bot_id: int
    invoice: any  # InputInvoiceMessage
    provider_url: Optional[str] = None  # URL for native payment
    native_provider: Optional[str] = None  # e.g., "stripe"
    native_params: Optional[dict] = None  # Provider-specific params
    saved_credentials: Optional[list] = None  # Saved payment methods
    amount: Optional[int] = None  # Amount in smallest currency unit
    currency: Optional[str] = None


def _get_http_proxy_url() -> Optional[str]:
    """Get HTTP proxy URL from settings for outbound requests."""
    settings = get_settings()
    return settings.security.http_proxy_url


class PremiumService:
    """Service for purchasing Telegram Premium."""

    def __init__(self, client: TelegramClient):
        self.client = client
        self._last_message: Optional[Message] = None
        self._payment_form: Optional[PaymentFormInfo] = None

    async def get_premium_invoice(self) -> dict:
        """
        Get invoice from PremiumBot.

        Returns:
            Dict with invoice info or error
        """
        try:
            # Get PremiumBot entity
            premium_bot = await self.client.get_entity(PREMIUM_BOT_USERNAME)

            # Send /start
            await self.client.send_message(premium_bot, "/start")
            await asyncio.sleep(2)

            # Get response with invoice
            messages = await self.client.get_messages(premium_bot, limit=3)
            if not messages:
                raise PremiumPurchaseError("No response from PremiumBot")

            # Find message with invoice
            for msg in messages:
                if msg.media and isinstance(msg.media, MessageMediaInvoice):
                    self._last_message = msg

                    invoice = msg.media
                    return {
                        "success": True,
                        "has_invoice": True,
                        "message_id": msg.id,
                        "title": invoice.title,
                        "description": invoice.description,
                        "currency": invoice.currency,
                        "total_amount": invoice.total_amount,
                        "amount_display": f"{invoice.total_amount / 100:.2f} {invoice.currency}",
                    }

            # No invoice found - check for buttons
            msg = messages[0]
            self._last_message = msg
            buttons = await self.get_current_buttons()

            logger.warning("No invoice found", buttons=buttons)
            raise PremiumPurchaseError(f"No invoice in response. Buttons: {[b['text'] for b in buttons]}")

        except PremiumPurchaseError:
            raise
        except Exception as e:
            logger.error("Get invoice error", error=str(e))
            raise PremiumPurchaseError(f"Error: {str(e)}")

    async def get_payment_form(self, message_id: int) -> PaymentFormInfo:
        """
        Get payment form for invoice.

        Args:
            message_id: Message ID with invoice

        Returns:
            PaymentFormInfo with form details
        """
        try:
            premium_bot = await self.client.get_entity(PREMIUM_BOT_USERNAME)

            # Convert to InputPeerUser for the API request
            input_peer = types.InputPeerUser(
                user_id=premium_bot.id,
                access_hash=premium_bot.access_hash,
            )

            # Create input invoice
            input_invoice = types.InputInvoiceMessage(
                peer=input_peer,
                msg_id=message_id,
            )

            # Get payment form
            result = await self.client(functions.payments.GetPaymentFormRequest(
                invoice=input_invoice,
            ))

            # Log all available fields for debugging
            logger.info(
                "Payment form received",
                form_id=result.form_id,
                bot_id=result.bot_id,
                native_provider=getattr(result, 'native_provider', None),
                has_saved_credentials=bool(getattr(result, 'saved_credentials', None)),
                url=getattr(result, 'url', None),
                native_params=str(getattr(result, 'native_params', None))[:200] if getattr(result, 'native_params', None) else None,
                result_type=type(result).__name__,
            )

            # Log all result attributes for debugging
            logger.debug(
                "Full payment form fields",
                fields=[attr for attr in dir(result) if not attr.startswith('_')],
            )

            # Extract native params (contains provider-specific data)
            # For Stripe: publishable_key
            # For Smart Glocal: public_token, tokenize_url
            native_params = None
            if hasattr(result, 'native_params') and result.native_params:
                try:
                    native_params = json.loads(result.native_params.data)
                    logger.info(
                        "Native params extracted",
                        native_params=native_params,
                    )
                except Exception as e:
                    logger.warning("Failed to parse native_params", error=str(e), raw=str(result.native_params)[:500])

            # Get invoice info
            invoice = result.invoice
            amount = None
            currency = None
            if invoice and hasattr(invoice, 'prices') and invoice.prices:
                amount = sum(p.amount for p in invoice.prices)
                currency = invoice.currency

            form_info = PaymentFormInfo(
                form_id=result.form_id,
                bot_id=result.bot_id,
                invoice=input_invoice,
                provider_url=getattr(result, 'url', None),
                native_provider=getattr(result, 'native_provider', None),
                native_params=native_params,
                saved_credentials=getattr(result, 'saved_credentials', None),
                amount=amount,
                currency=currency,
            )

            self._payment_form = form_info
            return form_info

        except Exception as e:
            logger.error("Get payment form error", error=str(e))
            raise PremiumPurchaseError(f"Failed to get payment form: {str(e)}")

    async def create_stripe_token(self, card: CardData, publishable_key: str) -> str:
        """
        Create Stripe token from card data.

        Args:
            card: Card data
            publishable_key: Stripe publishable key from payment form

        Returns:
            Stripe token ID
        """
        if not card.validate():
            raise PremiumPurchaseError("Invalid card data")

        async with httpx.AsyncClient(proxy=_get_http_proxy_url()) as http_client:
            response = await http_client.post(
                "https://api.stripe.com/v1/tokens",
                headers={
                    "Authorization": f"Bearer {publishable_key}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "card[number]": card.clean_number,
                    "card[exp_month]": str(card.exp_month),
                    "card[exp_year]": str(card.exp_year),
                    "card[cvc]": card.cvc,
                },
            )

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get("error", {}).get("message", "Unknown error")
                logger.error("Stripe token error", status=response.status_code, error=error_msg)
                raise PremiumPurchaseError(f"Card error: {error_msg}")

            data = response.json()
            token_id = data.get("id")
            token_type = data.get("type", "card")

            logger.info("Stripe token created", token_id=token_id[:20] + "...")
            return json.dumps({"type": token_type, "id": token_id})

    async def create_smart_glocal_token(
        self,
        card: CardData,
        tokenize_url: str,
        public_token: str,
    ) -> str:
        """
        Create Smart Glocal token from card data.

        Args:
            card: Card data
            tokenize_url: URL for tokenization from payment form
            public_token: Public token from payment form

        Returns:
            JSON string with token data for Telegram
        """
        if not card.validate():
            raise PremiumPurchaseError("Invalid card data")

        # Smart Glocal tokenization request
        # Based on TDLib paymentProviderSmartGlocal
        async with httpx.AsyncClient(proxy=_get_http_proxy_url()) as http_client:
            # The tokenize_url usually ends with something like /apm/tokenize/...
            # We need to POST card data to it
            payload = {
                "card": {
                    "number": card.clean_number,
                    "expiration_month": str(card.exp_month).zfill(2),
                    "expiration_year": str(card.exp_year),
                    "security_code": card.cvc,
                },
            }

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            # If public_token is provided, add it as authorization
            if public_token:
                headers["Authorization"] = f"Bearer {public_token}"

            logger.info(
                "Sending Smart Glocal tokenization request",
                tokenize_url=tokenize_url,
                has_public_token=bool(public_token),
            )

            response = await http_client.post(
                tokenize_url,
                json=payload,
                headers=headers,
                timeout=30.0,
            )

            logger.info(
                "Smart Glocal response",
                status=response.status_code,
                response_text=response.text[:500] if response.text else None,
            )

            if response.status_code != 200:
                # Try to parse error
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message") or error_data.get("error") or str(error_data)
                except:
                    error_msg = response.text[:200] if response.text else f"HTTP {response.status_code}"
                raise PremiumPurchaseError(f"Smart Glocal error: {error_msg}")

            data = response.json()

            # Extract token from response
            # Response format may vary, try common fields
            token = data.get("token") or data.get("data", {}).get("token")
            if not token:
                logger.warning("Smart Glocal response has no token", response_data=data)
                # Return the whole response as token data
                return json.dumps(data)

            logger.info("Smart Glocal token created", token=str(token)[:30] + "...")
            return json.dumps({"token": token})

    async def send_payment(
        self,
        form_info: PaymentFormInfo,
        credentials_data: str,
        save_credentials: bool = False,
    ) -> dict:
        """
        Send payment form with credentials.

        Args:
            form_info: Payment form info
            credentials_data: JSON string with Stripe token
            save_credentials: Whether to save card for future use

        Returns:
            Dict with result (success or 3DS URL)
        """
        try:
            # Create credentials
            credentials = types.InputPaymentCredentials(
                data=types.DataJSON(data=credentials_data),
                save=save_credentials,
            )

            # Send payment form
            result = await self.client(functions.payments.SendPaymentFormRequest(
                form_id=form_info.form_id,
                invoice=form_info.invoice,
                credentials=credentials,
            ))

            logger.info("Payment form sent", result_type=type(result).__name__)

            # Check result type
            if isinstance(result, types.payments.PaymentResult):
                # Payment successful!
                return {
                    "success": True,
                    "completed": True,
                    "message": "Payment completed successfully!",
                }

            elif isinstance(result, types.payments.PaymentVerificationNeeded):
                # Need 3DS verification
                return {
                    "success": True,
                    "completed": False,
                    "needs_verification": True,
                    "verification_url": result.url,
                    "message": "3DS verification required",
                }

            else:
                return {
                    "success": False,
                    "error": f"Unexpected result: {type(result).__name__}",
                }

        except Exception as e:
            logger.error("Send payment error", error=str(e))
            raise PremiumPurchaseError(f"Payment failed: {str(e)}")

    async def pay_with_card(
        self,
        message_id: int,
        card: CardData,
        save_card: bool = False,
    ) -> dict:
        """
        Complete payment flow with card.

        Args:
            message_id: Invoice message ID
            card: Card data
            save_card: Save card for future use

        Returns:
            Dict with result
        """
        # Step 1: Get payment form
        form_info = await self.get_payment_form(message_id)

        logger.info(
            "Processing payment",
            native_provider=form_info.native_provider,
            has_url=bool(form_info.provider_url),
            native_params_keys=list(form_info.native_params.keys()) if form_info.native_params else None,
        )

        # Check for Smart Glocal with tokenize_url (preferred method)
        if form_info.native_params:
            tokenize_url = form_info.native_params.get("tokenize_url")
            public_token = form_info.native_params.get("public_token")

            if tokenize_url:
                logger.info("Using Smart Glocal tokenization", tokenize_url=tokenize_url)

                # Step 2: Create Smart Glocal token
                token_data = await self.create_smart_glocal_token(card, tokenize_url, public_token)

                # Step 3: Send payment to Telegram
                result = await self.send_payment(form_info, token_data, save_card)
                return result

        # Check if Stripe native is supported
        if form_info.native_provider == "stripe":
            # Get Stripe publishable key
            if not form_info.native_params or "publishable_key" not in form_info.native_params:
                raise PremiumPurchaseError("No Stripe publishable key in payment form")

            publishable_key = form_info.native_params["publishable_key"]

            # Step 2: Create Stripe token
            token_data = await self.create_stripe_token(card, publishable_key)

            # Step 3: Send payment
            result = await self.send_payment(form_info, token_data, save_card)
            return result

        # Check if there's a URL for external payment (web-based checkout)
        # This is fallback - we try tokenization first
        if form_info.provider_url:
            logger.info("Payment form has external URL (fallback)", url=form_info.provider_url)
            return {
                "success": True,
                "completed": False,
                "has_url": True,
                "payment_url": form_info.provider_url,
                "message": "Use external payment URL",
            }

        # No supported payment method
        raise PremiumPurchaseError(
            f"Unsupported payment provider: {form_info.native_provider}. "
            f"Native params: {form_info.native_params}. "
            "No tokenize_url or Stripe publishable_key found."
        )

    async def pay_with_saved_card(
        self,
        message_id: int,
        credentials_id: str,
        tmp_password: bytes,
    ) -> dict:
        """
        Pay with saved card.

        Args:
            message_id: Invoice message ID
            credentials_id: Saved credentials ID
            tmp_password: Temporary password from account.getTmpPassword

        Returns:
            Dict with result
        """
        form_info = await self.get_payment_form(message_id)

        credentials = types.InputPaymentCredentialsSaved(
            id=credentials_id,
            tmp_password=tmp_password,
        )

        result = await self.client(functions.payments.SendPaymentFormRequest(
            form_id=form_info.form_id,
            invoice=form_info.invoice,
            credentials=credentials,
        ))

        if isinstance(result, types.payments.PaymentResult):
            return {"success": True, "completed": True, "message": "Payment completed!"}
        elif isinstance(result, types.payments.PaymentVerificationNeeded):
            return {
                "success": True,
                "completed": False,
                "needs_verification": True,
                "verification_url": result.url,
            }

        return {"success": False, "error": f"Unexpected: {type(result).__name__}"}

    async def check_premium_status(self) -> dict:
        """Check if current account has Premium."""
        try:
            me = await self.client.get_me()
            has_premium = getattr(me, 'premium', False)

            return {
                "success": True,
                "has_premium": has_premium,
                "user_id": me.id,
                "username": me.username,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_current_buttons(self) -> list[dict]:
        """Get current buttons from last message (for debugging)."""
        if not self._last_message:
            return []

        msg = self._last_message
        buttons = []

        if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
            for row in msg.reply_markup.rows:
                for button in row.buttons:
                    btn_info = {"text": getattr(button, 'text', 'N/A')}
                    if hasattr(button, 'url'):
                        btn_info["url"] = button.url
                    if hasattr(button, 'data'):
                        btn_info["data"] = button.data.hex() if button.data else None
                    if isinstance(button, KeyboardButtonBuy):
                        btn_info["type"] = "buy"
                    buttons.append(btn_info)

        return buttons


async def get_payment_url_for_account(
    account_id: UUID,
    session,
    message_id: int,
    proxy_config: Optional[dict] = None,
) -> dict:
    """
    Get payment URL for premium invoice.

    Returns URL for external payment (Smart Glocal).
    """
    from telethon.sessions import StringSession
    import python_socks

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        return {"success": False, "error": "Account not found"}

    # Decrypt session
    encryption = get_session_encryption()
    try:
        decrypted = encryption.decrypt(account.session_data)
        session_string = decrypted.decode('utf-8')
    except Exception as e:
        return {"success": False, "error": f"Failed to decrypt session: {e}"}

    settings = get_settings()

    # Build proxy if provided
    proxy = None
    if proxy_config:
        proxy = {
            'proxy_type': python_socks.ProxyType.SOCKS5,
            'addr': proxy_config['host'],
            'port': proxy_config['port'],
            'username': proxy_config.get('username'),
            'password': proxy_config.get('password'),
            'rdns': True,
        }

    client = TelegramClient(
        StringSession(session_string),
        settings.telegram.api_id,
        settings.telegram.api_hash.get_secret_value(),
        proxy=proxy,
    )

    try:
        await client.connect()

        if not await client.is_user_authorized():
            return {"success": False, "error": "Session is not authorized"}

        service = PremiumService(client)
        form_info = await service.get_payment_form(message_id)

        # Log what we got
        logger.info(
            "Payment form parsed",
            has_url=bool(form_info.provider_url),
            native_provider=form_info.native_provider,
            has_native_params=bool(form_info.native_params),
            native_params_keys=list(form_info.native_params.keys()) if form_info.native_params else None,
        )

        # Check if we have tokenize_url (Smart Glocal with direct card input)
        if form_info.native_params:
            tokenize_url = form_info.native_params.get("tokenize_url")
            public_token = form_info.native_params.get("public_token")
            if tokenize_url:
                # We can tokenize card directly - need card input
                return {
                    "success": True,
                    "payment_url": None,  # No external URL needed
                    "native_provider": "smartglocal",
                    "native_params": form_info.native_params,
                    "can_tokenize": True,
                    "form_id": form_info.form_id,
                    "bot_id": form_info.bot_id,
                    "public_token": public_token,
                    "session_string": session_string,
                    "amount": form_info.amount,
                    "currency": form_info.currency,
                }

        if form_info.provider_url:
            # Try to extract public_token from URL if it's a Smart Glocal URL
            public_token = None
            if "smart-glocal" in form_info.provider_url and "/tokenize/" in form_info.provider_url:
                public_token = extract_public_token_from_url(form_info.provider_url)

            return {
                "success": True,
                "payment_url": form_info.provider_url,
                "native_provider": form_info.native_provider,
                "native_params": form_info.native_params,
                "form_id": form_info.form_id,
                "bot_id": form_info.bot_id,
                "public_token": public_token,
                "session_string": session_string,
                "amount": form_info.amount,
                "currency": form_info.currency,
                "can_tokenize": bool(public_token),
            }
        elif form_info.native_provider == "stripe" and form_info.native_params:
            # Stripe native available - no URL, need card input
            return {
                "success": True,
                "payment_url": None,
                "native_provider": "stripe",
                "native_params": form_info.native_params,
                "form_id": form_info.form_id,
                "bot_id": form_info.bot_id,
                "session_string": session_string,
                "amount": form_info.amount,
                "currency": form_info.currency,
            }
        else:
            return {
                "success": False,
                "error": f"No payment URL and unsupported provider: {form_info.native_provider}",
                "native_params": form_info.native_params,
            }

    except PremiumPurchaseError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Get payment URL failed", account_id=str(account_id), error=str(e))
        return {"success": False, "error": f"Unexpected error: {str(e)}"}
    finally:
        await client.disconnect()


async def get_premium_invoice_for_account(
    account_id: UUID,
    session,
    proxy_config: Optional[dict] = None,
) -> dict:
    """
    Get premium invoice for account.

    Returns invoice info needed for payment.
    """
    from telethon.sessions import StringSession
    import python_socks

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        return {"success": False, "error": "Account not found"}

    # Decrypt session
    encryption = get_session_encryption()
    try:
        decrypted = encryption.decrypt(account.session_data)
        session_string = decrypted.decode('utf-8')
    except Exception as e:
        return {"success": False, "error": f"Failed to decrypt session: {e}"}

    settings = get_settings()

    # Build proxy if provided
    proxy = None
    if proxy_config:
        proxy = {
            'proxy_type': python_socks.ProxyType.SOCKS5,
            'addr': proxy_config['host'],
            'port': proxy_config['port'],
            'username': proxy_config.get('username'),
            'password': proxy_config.get('password'),
            'rdns': True,
        }

    client = TelegramClient(
        StringSession(session_string),
        settings.telegram.api_id,
        settings.telegram.api_hash.get_secret_value(),
        proxy=proxy,
    )

    try:
        await client.connect()

        if not await client.is_user_authorized():
            return {"success": False, "error": "Session is not authorized"}

        service = PremiumService(client)
        result = await service.get_premium_invoice()

        return result

    except PremiumPurchaseError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Get invoice failed", account_id=str(account_id), error=str(e))
        return {"success": False, "error": f"Unexpected error: {str(e)}"}
    finally:
        await client.disconnect()


async def pay_premium_with_card(
    account_id: UUID,
    session,
    message_id: int,
    card: CardData,
    save_card: bool = False,
    proxy_config: Optional[dict] = None,
) -> dict:
    """
    Pay for premium with card.

    Args:
        account_id: Account UUID
        session: Database session
        message_id: Invoice message ID
        card: Card data
        save_card: Save card for future use
        proxy_config: Proxy configuration

    Returns:
        Dict with result
    """
    from telethon.sessions import StringSession
    import python_socks

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        return {"success": False, "error": "Account not found"}

    encryption = get_session_encryption()
    try:
        decrypted = encryption.decrypt(account.session_data)
        session_string = decrypted.decode('utf-8')
    except Exception as e:
        return {"success": False, "error": f"Failed to decrypt session: {e}"}

    settings = get_settings()

    proxy = None
    if proxy_config:
        proxy = {
            'proxy_type': python_socks.ProxyType.SOCKS5,
            'addr': proxy_config['host'],
            'port': proxy_config['port'],
            'username': proxy_config.get('username'),
            'password': proxy_config.get('password'),
            'rdns': True,
        }

    client = TelegramClient(
        StringSession(session_string),
        settings.telegram.api_id,
        settings.telegram.api_hash.get_secret_value(),
        proxy=proxy,
    )

    try:
        await client.connect()

        if not await client.is_user_authorized():
            return {"success": False, "error": "Session is not authorized"}

        service = PremiumService(client)
        result = await service.pay_with_card(message_id, card, save_card)

        return result

    except PremiumPurchaseError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Payment failed", account_id=str(account_id), error=str(e))
        return {"success": False, "error": f"Unexpected error: {str(e)}"}
    finally:
        await client.disconnect()


async def check_premium_status(
    account_id: UUID,
    session,
    proxy_config: Optional[dict] = None,
) -> dict:
    """Check if account has Premium."""
    from telethon.sessions import StringSession
    import python_socks

    repo = PostgresAccountRepository(session)
    account = await repo.get_by_id(account_id)

    if not account:
        return {"success": False, "error": "Account not found"}

    encryption = get_session_encryption()
    try:
        decrypted = encryption.decrypt(account.session_data)
        session_string = decrypted.decode('utf-8')
    except Exception as e:
        return {"success": False, "error": f"Failed to decrypt session: {e}"}

    settings = get_settings()

    proxy = None
    if proxy_config:
        proxy = {
            'proxy_type': python_socks.ProxyType.SOCKS5,
            'addr': proxy_config['host'],
            'port': proxy_config['port'],
            'username': proxy_config.get('username'),
            'password': proxy_config.get('password'),
            'rdns': True,
        }

    client = TelegramClient(
        StringSession(session_string),
        settings.telegram.api_id,
        settings.telegram.api_hash.get_secret_value(),
        proxy=proxy,
    )

    try:
        await client.connect()

        if not await client.is_user_authorized():
            return {"success": False, "error": "Session is not authorized"}

        service = PremiumService(client)
        return await service.check_premium_status()

    except Exception as e:
        logger.error("Check premium failed", account_id=str(account_id), error=str(e))
        return {"success": False, "error": f"Unexpected error: {str(e)}"}
    finally:
        await client.disconnect()
