"""
Premium payment routes - card payment form and tokenization.
"""

import json
import secrets
import base64
import re
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import httpx
import python_socks
import structlog

from src.config import get_settings

logger = structlog.get_logger(__name__)


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

router = APIRouter()

# Redis-based payment session storage
import redis.asyncio as aioredis

PAYMENT_SESSION_TTL = 3600  # 1 hour

def _get_redis_sync():
    """Get sync Redis client."""
    import redis
    from src.config import get_settings
    settings = get_settings()
    return redis.Redis.from_url(str(settings.redis.url), decode_responses=True)

async def _get_redis():
    """Get async Redis client."""
    from src.config import get_settings
    settings = get_settings()
    return await aioredis.from_url(str(settings.redis.url), decode_responses=True)


class CardData(BaseModel):
    """Card data for tokenization."""
    session_id: str
    card_number: str
    expiry_month: str
    expiry_year: str
    cvv: str


class PaymentSession(BaseModel):
    """Payment session data."""
    account_id: str
    form_id: int
    public_token: str
    amount: str
    currency: str
    recipient_name: str
    bot_id: int


def create_payment_session(
    account_id: str,
    form_id: int,
    public_token: str,
    amount: str,
    currency: str,
    recipient_name: str,
    bot_id: int,
    message_id: int,
    session_string: str,  # Encrypted session for Telethon
    proxy_config: Optional[dict] = None,  # Proxy config for Telethon connection
) -> str:
    """Create a new payment session and return session ID (sync version for bot)."""
    session_id = secrets.token_urlsafe(32)
    session_data = {
        "account_id": account_id,
        "form_id": form_id,
        "public_token": public_token,
        "amount": amount,
        "currency": currency,
        "recipient_name": recipient_name,
        "bot_id": bot_id,
        "message_id": message_id,
        "session_string": session_string,
        "proxy_config": proxy_config,  # Store proxy for payment execution
        "status": "pending",
        "token": None,
        "error": None,
        "verification_url": None,
    }

    redis_client = _get_redis_sync()
    redis_client.setex(
        f"payment_session:{session_id}",
        PAYMENT_SESSION_TTL,
        json.dumps(session_data),
    )
    redis_client.close()

    logger.info(
        "Payment session created in Redis",
        session_id=session_id,
        account_id=account_id,
    )
    return session_id


async def get_payment_session(session_id: str) -> Optional[dict]:
    """Get payment session by ID from Redis."""
    redis_client = await _get_redis()
    try:
        data = await redis_client.get(f"payment_session:{session_id}")
        if data:
            return json.loads(data)
        return None
    finally:
        await redis_client.close()


async def update_payment_session(session_id: str, **kwargs):
    """Update payment session in Redis."""
    redis_client = await _get_redis()
    try:
        data = await redis_client.get(f"payment_session:{session_id}")
        if data:
            session_data = json.loads(data)
            session_data.update(kwargs)
            await redis_client.setex(
                f"payment_session:{session_id}",
                PAYMENT_SESSION_TTL,
                json.dumps(session_data),
            )
    finally:
        await redis_client.close()


PAYMENT_FORM_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Оплата Telegram Premium</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }

        .container {
            background: white;
            border-radius: 16px;
            padding: 32px;
            max-width: 420px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }

        .header {
            text-align: center;
            margin-bottom: 24px;
        }

        .header h1 {
            font-size: 24px;
            color: #1a1a2e;
            margin-bottom: 8px;
        }

        .header .recipient {
            font-size: 18px;
            color: #667eea;
            font-weight: 600;
        }

        .amount-badge {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 12px 24px;
            border-radius: 50px;
            display: inline-block;
            font-size: 20px;
            font-weight: 700;
            margin: 16px 0;
        }

        .star-icon {
            width: 80px;
            height: 80px;
            margin: 0 auto 16px;
            display: block;
        }

        .warning {
            background: #fff3cd;
            border: 1px solid #ffc107;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 20px;
            font-size: 13px;
            color: #856404;
        }

        .form-group {
            margin-bottom: 16px;
        }

        .form-group label {
            display: block;
            font-size: 14px;
            color: #666;
            margin-bottom: 6px;
        }

        .form-group input {
            width: 100%;
            padding: 14px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 16px;
            transition: border-color 0.2s;
        }

        .form-group input:focus {
            outline: none;
            border-color: #667eea;
        }

        .row {
            display: flex;
            gap: 12px;
        }

        .row .form-group {
            flex: 1;
        }

        .btn {
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            margin-top: 8px;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
        }

        .btn:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
        }

        .btn.loading {
            position: relative;
            color: transparent;
        }

        .btn.loading::after {
            content: "";
            position: absolute;
            width: 24px;
            height: 24px;
            top: 50%;
            left: 50%;
            margin-left: -12px;
            margin-top: -12px;
            border: 3px solid white;
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .secure-note {
            text-align: center;
            margin-top: 16px;
            font-size: 12px;
            color: #999;
        }

        .secure-note svg {
            vertical-align: middle;
            margin-right: 4px;
        }

        .error-message {
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 16px;
            display: none;
        }

        .success-message {
            background: #d4edda;
            border: 1px solid #c3e6cb;
            color: #155724;
            padding: 16px;
            border-radius: 8px;
            text-align: center;
            display: none;
        }

        .redirect-message {
            background: #e7f1ff;
            border: 1px solid #b6d4fe;
            color: #084298;
            padding: 16px;
            border-radius: 8px;
            text-align: center;
            display: none;
        }

        .redirect-message a {
            color: #0d6efd;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <svg class="star-icon" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <defs>
                    <linearGradient id="starGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" style="stop-color:#667eea"/>
                        <stop offset="100%" style="stop-color:#764ba2"/>
                    </linearGradient>
                </defs>
                <path d="M50 5 L61 39 L97 39 L68 61 L79 95 L50 73 L21 95 L32 61 L3 39 L39 39 Z" fill="url(#starGrad)"/>
            </svg>
            <h1>Telegram Premium</h1>
            <div class="recipient">для {recipient_name}</div>
            <div class="amount-badge">{amount} {currency}</div>
        </div>

        <div class="warning">
            ⚠️ Мы не храним данные карты. Они передаются напрямую в защищённую платёжную систему Telegram.
        </div>

        <div class="error-message" id="error"></div>
        <div class="success-message" id="success">
            ✅ Оплата прошла успешно! Premium активирован.
        </div>
        <div class="redirect-message" id="redirect">
            🔐 Требуется подтверждение 3D Secure<br><br>
            <a href="#" id="redirect-link" target="_blank">Подтвердить платёж →</a>
        </div>

        <form id="payment-form">
            <div class="form-group">
                <label>Номер карты</label>
                <input type="text" id="card_number" placeholder="0000 0000 0000 0000"
                       maxlength="19" autocomplete="cc-number" inputmode="numeric" required>
            </div>

            <div class="row">
                <div class="form-group">
                    <label>Месяц</label>
                    <input type="text" id="expiry_month" placeholder="MM"
                           maxlength="2" autocomplete="cc-exp-month" inputmode="numeric" required>
                </div>
                <div class="form-group">
                    <label>Год</label>
                    <input type="text" id="expiry_year" placeholder="YY"
                           maxlength="2" autocomplete="cc-exp-year" inputmode="numeric" required>
                </div>
                <div class="form-group">
                    <label>CVV</label>
                    <input type="text" id="cvv" placeholder="000"
                           maxlength="4" autocomplete="cc-csc" inputmode="numeric" required>
                </div>
            </div>

            <button type="submit" class="btn" id="submit-btn">Оплатить</button>
        </form>

        <div class="secure-note">
            <svg width="12" height="14" viewBox="0 0 12 14" fill="currentColor">
                <path d="M10 5V4C10 1.79 8.21 0 6 0S2 1.79 2 4v1C0.9 5 0 5.9 0 7v5c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zM6 11c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zM8 5H4V4c0-1.1.9-2 2-2s2 .9 2 2v1z"/>
            </svg>
            Защищённое соединение · Данные шифруются
        </div>
    </div>

    <script>
        const sessionId = "{session_id}";
        const form = document.getElementById('payment-form');
        const cardInput = document.getElementById('card_number');
        const submitBtn = document.getElementById('submit-btn');
        const errorDiv = document.getElementById('error');
        const successDiv = document.getElementById('success');
        const redirectDiv = document.getElementById('redirect');
        const redirectLink = document.getElementById('redirect-link');

        // Format card number with spaces
        cardInput.addEventListener('input', function(e) {
            let value = e.target.value.replace(/\\s/g, '').replace(/\\D/g, '');
            let formatted = value.match(/.{1,4}/g)?.join(' ') || value;
            e.target.value = formatted;
        });

        // Only allow numbers
        ['expiry_month', 'expiry_year', 'cvv'].forEach(id => {
            document.getElementById(id).addEventListener('input', function(e) {
                e.target.value = e.target.value.replace(/\\D/g, '');
            });
        });

        form.addEventListener('submit', async function(e) {
            e.preventDefault();

            errorDiv.style.display = 'none';
            submitBtn.classList.add('loading');
            submitBtn.disabled = true;

            const cardNumber = cardInput.value.replace(/\\s/g, '');
            const expiryMonth = document.getElementById('expiry_month').value.padStart(2, '0');
            const expiryYear = document.getElementById('expiry_year').value.padStart(2, '0');
            const cvv = document.getElementById('cvv').value;

            try {
                const response = await fetch('/api/v1/premium/process', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        session_id: sessionId,
                        card_number: cardNumber,
                        expiry_month: expiryMonth,
                        expiry_year: expiryYear,
                        cvv: cvv,
                    }),
                });

                const result = await response.json();

                if (result.success) {
                    form.style.display = 'none';
                    successDiv.style.display = 'block';
                } else if (result.needs_verification && result.verification_url) {
                    form.style.display = 'none';
                    redirectLink.href = result.verification_url;
                    redirectDiv.style.display = 'block';
                } else {
                    errorDiv.textContent = result.error || 'Ошибка оплаты. Попробуйте ещё раз.';
                    errorDiv.style.display = 'block';
                }
            } catch (err) {
                errorDiv.textContent = 'Ошибка соединения. Попробуйте ещё раз.';
                errorDiv.style.display = 'block';
            } finally {
                submitBtn.classList.remove('loading');
                submitBtn.disabled = false;
            }
        });
    </script>
</body>
</html>
"""


@router.get("/pay/{session_id}", response_class=HTMLResponse)
async def payment_form_page(session_id: str):
    """Render payment form page."""
    session = await get_payment_session(session_id)

    if not session:
        return HTMLResponse(
            content="<h1>Сессия оплаты не найдена или истекла</h1>",
            status_code=404,
        )

    if session.get("status") == "completed":
        return HTMLResponse(
            content="<h1>Эта оплата уже завершена</h1>",
            status_code=400,
        )

    html = PAYMENT_FORM_HTML.replace(
        "{session_id}", session_id
    ).replace(
        "{recipient_name}", session.get("recipient_name", "Unknown")
    ).replace(
        "{amount}", session.get("amount", "0")
    ).replace(
        "{currency}", session.get("currency", "RUB")
    )

    return HTMLResponse(content=html)


@router.post("/process")
async def process_payment(card_data: CardData):
    """Process card payment - tokenize and send payment form."""
    from telethon import TelegramClient, functions, types
    from telethon.sessions import StringSession
    from src.config import get_settings

    session = await get_payment_session(card_data.session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Payment session not found")

    if session.get("status") == "completed":
        raise HTTPException(status_code=400, detail="Payment already completed")

    public_token = session.get("public_token")
    if not public_token:
        return JSONResponse(content={
            "success": False,
            "error": "Missing public token for tokenization",
        })

    # Step 1: Tokenize card via Smart Glocal
    tokenize_url = "https://tgb.smart-glocal.com/cds/v1/tokenize/card"

    tokenize_payload = {
        "card": {
            "number": card_data.card_number,
            "expiration_month": card_data.expiry_month,
            "expiration_year": card_data.expiry_year,
            "security_code": card_data.cvv,
        }
    }

    logger.info(
        "Tokenizing card",
        session_id=card_data.session_id,
    )

    token = None
    try:
        settings = get_settings()
        proxy_url = settings.security.http_proxy_url
        async with httpx.AsyncClient(proxy=proxy_url) as http_client:
            tokenize_response = await http_client.post(
                tokenize_url,
                json=tokenize_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-PUBLIC-TOKEN": public_token,
                },
                timeout=30.0,
            )

            logger.info(
                "Tokenize response",
                status_code=tokenize_response.status_code,
                response=tokenize_response.text[:500],
            )

            if tokenize_response.status_code != 200:
                error_text = tokenize_response.text[:200]
                return JSONResponse(content={
                    "success": False,
                    "error": f"Ошибка токенизации карты: {error_text}",
                })

            tokenize_result = tokenize_response.json()
            token = tokenize_result.get("data", {}).get("token")

            if not token:
                return JSONResponse(content={
                    "success": False,
                    "error": "Не удалось получить токен карты",
                })

            await update_payment_session(card_data.session_id, token=token, status="tokenized")
            logger.info("Card tokenized successfully", token=token[:20] + "...")

    except Exception as e:
        logger.error("Tokenization error", error=str(e))
        return JSONResponse(content={
            "success": False,
            "error": f"Ошибка токенизации: {str(e)}",
        })

    # Step 2: Send payment form via Telethon
    session_string = session.get("session_string")
    message_id = session.get("message_id")
    form_id = session.get("form_id")
    bot_id = session.get("bot_id")
    proxy_config = session.get("proxy_config")

    if not session_string:
        return JSONResponse(content={
            "success": False,
            "error": "Session string not found",
        })

    # Anti-detection: MUST use proxy for Telegram connection
    if not proxy_config:
        logger.error("No proxy config in payment session - cannot proceed without proxy")
        return JSONResponse(content={
            "success": False,
            "error": "Proxy configuration missing - payment requires proxy",
        })

    settings = get_settings()

    # Build proxy dict for Telethon
    proxy_dict = {
        'proxy_type': python_socks.ProxyType.SOCKS5,
        'addr': proxy_config['host'],
        'port': proxy_config['port'],
        'username': proxy_config.get('username'),
        'password': proxy_config.get('password'),
        'rdns': True,
    }

    tg_client = TelegramClient(
        StringSession(session_string),
        settings.telegram.api_id,
        settings.telegram.api_hash.get_secret_value(),
        proxy=proxy_dict,  # CRITICAL: Use proxy to avoid IP leak
    )

    try:
        await tg_client.connect()

        if not await tg_client.is_user_authorized():
            return JSONResponse(content={
                "success": False,
                "error": "Telegram session expired",
            })

        # Get PremiumBot entity for invoice
        premium_bot = await tg_client.get_entity("PremiumBot")
        input_peer = types.InputPeerUser(
            user_id=premium_bot.id,
            access_hash=premium_bot.access_hash,
        )

        # Create input invoice
        input_invoice = types.InputInvoiceMessage(
            peer=input_peer,
            msg_id=message_id,
        )

        # Create credentials with token
        # Smart Glocal format for Telegram
        credentials_data = json.dumps({
            "type": "card",
            "token": token,
        })
        credentials = types.InputPaymentCredentials(
            data=types.DataJSON(data=credentials_data),
            save=False,
        )

        logger.info(
            "Credentials prepared",
            credentials_data=credentials_data,
        )

        logger.info(
            "Sending payment form",
            form_id=form_id,
            message_id=message_id,
        )

        # Send payment form
        result = await tg_client(functions.payments.SendPaymentFormRequest(
            form_id=form_id,
            invoice=input_invoice,
            credentials=credentials,
        ))

        logger.info("Payment form result", result_type=type(result).__name__)

        # Check result
        if isinstance(result, types.payments.PaymentResult):
            await update_payment_session(card_data.session_id, status="completed")
            return JSONResponse(content={
                "success": True,
                "message": "Оплата прошла успешно! Premium активирован.",
            })

        elif isinstance(result, types.payments.PaymentVerificationNeeded):
            await update_payment_session(
                card_data.session_id,
                status="verification_needed",
                verification_url=result.url,
            )
            return JSONResponse(content={
                "success": False,
                "needs_verification": True,
                "verification_url": result.url,
                "message": "Требуется подтверждение 3DS",
            })

        else:
            return JSONResponse(content={
                "success": False,
                "error": f"Неожиданный результат: {type(result).__name__}",
            })

    except Exception as e:
        logger.error("Payment error", error=str(e))
        await update_payment_session(card_data.session_id, status="error", error=str(e))
        return JSONResponse(content={
            "success": False,
            "error": f"Ошибка оплаты: {str(e)}",
        })

    finally:
        await tg_client.disconnect()


@router.get("/status/{session_id}")
async def payment_status(session_id: str):
    """Check payment session status."""
    session = await get_payment_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Payment session not found")

    return {
        "status": session.get("status"),
        "error": session.get("error"),
    }
