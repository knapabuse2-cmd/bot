"""
Accounts API routes.
"""

import io
import os
import tempfile
import zipfile
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form

from src.application.services import AccountService
import structlog

from src.domain.entities import AccountStatus
from src.domain.exceptions import AccountNotFoundError, DomainException

logger = structlog.get_logger(__name__)

from ..dependencies import get_account_service, get_account_repo, get_proxy_repo
from ..schemas import (
    AccountCreate,
    AccountUpdate,
    AccountResponse,
    AccountListResponse,
    AccountScheduleUpdate,
    AccountLimitsUpdate,
)

router = APIRouter()


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    status: Optional[str] = Query(None, description="Filter by status"),
    campaign_id: Optional[UUID] = Query(None, description="Filter by campaign"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: AccountService = Depends(get_account_service),
):
    """List all accounts with optional filters."""
    repo = service._account_repo
    
    if status:
        try:
            account_status = AccountStatus(status)
            accounts = await repo.list_by_status(account_status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")
    elif campaign_id:
        accounts = await repo.list_by_campaign(campaign_id)
    else:
        accounts = await repo.list_all(limit=per_page * page)
    
    # Pagination
    total = len(accounts)
    start = (page - 1) * per_page
    end = start + per_page
    paginated = accounts[start:end]
    
    return AccountListResponse(
        items=[AccountResponse.model_validate(a) for a in paginated],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page,
    )


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Get account by ID."""
    try:
        account = await service.get_account(account_id)
        return AccountResponse.model_validate(account)
    except AccountNotFoundError:
        raise HTTPException(404, "Account not found")


@router.post("", response_model=AccountResponse, status_code=201)
async def create_account(
    data: AccountCreate,
    service: AccountService = Depends(get_account_service),
):
    """Create a new account."""
    try:
        account = await service.create_account(
            phone=data.phone,
            session_data=data.session_data,
        )
        
        if data.proxy_id:
            await service.assign_proxy(account.id, data.proxy_id)
            account = await service.get_account(account.id)
        
        return AccountResponse.model_validate(account)
    except DomainException as e:
        raise HTTPException(400, e.code)
    except Exception as e:
        logger.error("Error creating account", error=str(e))
        raise HTTPException(400, "Failed to create account")


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: UUID,
    data: AccountUpdate,
    service: AccountService = Depends(get_account_service),
):
    """Update account."""
    try:
        account = await service.get_account(account_id)

        if data.proxy_id:
            await service.assign_proxy(account_id, data.proxy_id)

        if data.status == "active":
            await service.activate_account(account_id)
        elif data.status == "paused":
            await service.pause_account(account_id)

        return AccountResponse.model_validate(
            await service.get_account(account_id)
        )
    except AccountNotFoundError:
        raise HTTPException(404, "Account not found")
    except DomainException as e:
        raise HTTPException(400, e.code)
    except Exception as e:
        logger.error("Error updating account", account_id=str(account_id), error=str(e))
        raise HTTPException(400, "Failed to update account")


@router.post("/{account_id}/activate", response_model=AccountResponse)
async def activate_account(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Activate an account."""
    try:
        account = await service.activate_account(account_id)
        return AccountResponse.model_validate(account)
    except AccountNotFoundError:
        raise HTTPException(404, "Account not found")
    except DomainException as e:
        raise HTTPException(400, e.code)
    except Exception as e:
        logger.error("Error activating account", account_id=str(account_id), error=str(e))
        raise HTTPException(400, "Failed to activate account")


@router.post("/{account_id}/pause", response_model=AccountResponse)
async def pause_account(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Pause an account."""
    try:
        account = await service.pause_account(account_id)
        return AccountResponse.model_validate(account)
    except AccountNotFoundError:
        raise HTTPException(404, "Account not found")


@router.patch("/{account_id}/schedule", response_model=AccountResponse)
async def update_account_schedule(
    account_id: UUID,
    data: AccountScheduleUpdate,
    service: AccountService = Depends(get_account_service),
):
    """Update account schedule."""
    try:
        account = await service.get_account(account_id)
        
        # Update schedule fields
        if data.start_time:
            account.schedule.start_time = datetime.strptime(data.start_time, "%H:%M").time()
        if data.end_time:
            account.schedule.end_time = datetime.strptime(data.end_time, "%H:%M").time()
        if data.active_days:
            account.schedule.active_days = data.active_days
        if data.timezone:
            account.schedule.timezone = data.timezone
        
        await service._account_repo.save(account)
        
        return AccountResponse.model_validate(account)
    except AccountNotFoundError:
        raise HTTPException(404, "Account not found")


@router.patch("/{account_id}/limits", response_model=AccountResponse)
async def update_account_limits(
    account_id: UUID,
    data: AccountLimitsUpdate,
    service: AccountService = Depends(get_account_service),
):
    """Update account limits."""
    try:
        account = await service.get_account(account_id)
        
        # Update limit fields
        if data.max_messages_per_hour is not None:
            account.limits.max_messages_per_hour = data.max_messages_per_hour
        if data.max_new_conversations_per_day is not None:
            account.limits.max_new_conversations_per_day = data.max_new_conversations_per_day
        if data.min_delay_between_messages is not None:
            account.limits.min_delay_between_messages = data.min_delay_between_messages
        if data.max_delay_between_messages is not None:
            account.limits.max_delay_between_messages = data.max_delay_between_messages
        
        await service._account_repo.save(account)
        
        return AccountResponse.model_validate(account)
    except AccountNotFoundError:
        raise HTTPException(404, "Account not found")


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Delete an account."""
    deleted = await service._account_repo.delete(account_id)
    if not deleted:
        raise HTTPException(404, "Account not found")


@router.get("/{account_id}/stats")
async def get_account_stats(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Get account statistics."""
    try:
        account = await service.get_account(account_id)
        
        return {
            "account_id": str(account.id),
            "hourly_messages": account.hourly_messages_count,
            "hourly_limit": account.limits.max_messages_per_hour,
            "daily_conversations": account.daily_conversations_count,
            "daily_limit": account.limits.max_new_conversations_per_day,
            "total_messages_sent": account.total_messages_sent,
            "total_conversations_started": account.total_conversations_started,
            "can_send_message": account.can_send_message(),
            "can_start_conversation": account.can_start_new_conversation(),
            "last_activity": account.last_activity.isoformat() if account.last_activity else None,
        }
    except AccountNotFoundError:
        raise HTTPException(404, "Account not found")


@router.post("/{account_id}/premium/purchase")
async def purchase_premium(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """
    Start Premium subscription purchase for account.

    Returns payment URL for 3DS confirmation.
    """
    from src.application.services.premium_service import PremiumService
    from src.infrastructure.database.repositories import PostgresProxyRepository

    try:
        account = await service.get_account(account_id)
    except AccountNotFoundError:
        raise HTTPException(404, "Account not found")

    # Get proxy if assigned
    proxy_host = None
    proxy_port = None
    proxy_username = None
    proxy_password = None

    if account.proxy_id:
        try:
            # Get proxy details from repo
            repo = service._account_repo
            proxy_repo = PostgresProxyRepository(repo._session)
            proxy = await proxy_repo.get_by_id(account.proxy_id)
            if proxy:
                proxy_host = proxy.host
                proxy_port = proxy.port
                proxy_username = proxy.username
                proxy_password = proxy.password
        except Exception:
            pass

    premium_service = PremiumService()
    result = await premium_service.purchase_premium(
        account=account,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        proxy_username=proxy_username,
        proxy_password=proxy_password,
    )

    if result.success:
        return {
            "success": True,
            "payment_url": result.payment_url,
            "message": result.message,
        }
    else:
        raise HTTPException(400, result.error)


@router.get("/{account_id}/premium/status")
async def check_premium_status(
    account_id: UUID,
    service: AccountService = Depends(get_account_service),
):
    """Check if account has active Premium subscription."""
    from src.application.services.premium_service import PremiumService

    try:
        account = await service.get_account(account_id)
    except AccountNotFoundError:
        raise HTTPException(404, "Account not found")

    premium_service = PremiumService()
    is_premium = await premium_service.check_premium_status(account)

    # Update account premium status in DB
    if is_premium != account.is_premium:
        account.is_premium = is_premium
        await service._account_repo.save(account)

    return {
        "account_id": str(account_id),
        "is_premium": is_premium,
    }


@router.post("/import/zip", response_model=AccountResponse, status_code=201)
async def import_account_from_zip(
    file: UploadFile = File(...),
    proxy_id: Optional[UUID] = Form(None),
    service: AccountService = Depends(get_account_service),
):
    """
    Import account from ZIP archive.

    Supports:
    - tdata (Telegram Desktop data)
    - Telethon session + json
    """
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import SessionPasswordNeededError
    from src.config import get_settings
    from src.infrastructure.database.repositories import PostgresProxyRepository
    import python_socks
    import shutil

    if not file.filename.endswith(".zip"):
        raise HTTPException(400, "File must be a .zip archive")

    temp_dir = None
    client = None

    try:
        # Read file
        zip_bytes = await file.read()

        # Create temp directory
        temp_dir = tempfile.mkdtemp()

        # Extract ZIP
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
                zf.extractall(temp_dir)
        except zipfile.BadZipFile:
            raise HTTPException(400, "Invalid ZIP archive")

        # Check if tdata or session
        is_tdata = _check_is_tdata(temp_dir)

        if is_tdata:
            account_data = await _convert_tdata_to_session(temp_dir)
        else:
            account_data = await _parse_session_files(temp_dir)

        if not account_data:
            raise HTTPException(
                400,
                "Could not extract account data. Archive must contain tdata folder or .session file"
            )

        session_string = account_data.get("session_string")
        session_bytes = account_data.get("session_bytes")

        if not session_string and not session_bytes:
            raise HTTPException(400, "Could not extract session from archive")

        settings = get_settings()

        # Build proxy config if provided
        proxy_dict = None
        proxy = None
        if proxy_id:
            proxy = await service._account_repo.get_proxy_by_id(proxy_id)
            if proxy:
                proxy_dict = {
                    'proxy_type': python_socks.ProxyType.SOCKS5,
                    'addr': proxy.host,
                    'port': proxy.port,
                    'username': proxy.username,
                    'password': proxy.password,
                    'rdns': True,
                }

        # Create Telethon client
        if session_string:
            client = TelegramClient(
                StringSession(session_string),
                settings.telegram.api_id,
                settings.telegram.api_hash.get_secret_value(),
                proxy=proxy_dict,
            )
        else:
            # SQLite session - convert first
            temp_session_path = os.path.join(temp_dir, "temp_session")
            with open(temp_session_path + ".session", 'wb') as f:
                f.write(session_bytes)

            converted = await _convert_session_to_telethon_string(temp_session_path + ".session")
            if converted:
                session_string = converted
                client = TelegramClient(
                    StringSession(session_string),
                    settings.telegram.api_id,
                    settings.telegram.api_hash.get_secret_value(),
                    proxy=proxy_dict,
                )
            else:
                client = TelegramClient(
                    temp_session_path,
                    settings.telegram.api_id,
                    settings.telegram.api_hash.get_secret_value(),
                    proxy=proxy_dict,
                )

        # Connect and validate
        await client.connect()

        if not await client.is_user_authorized():
            raise HTTPException(401, "Session is invalid or expired")

        # Get user info
        me = await client.get_me()

        phone = f"+{me.phone}" if me.phone else account_data.get("phone", "")
        if phone and not phone.startswith("+"):
            phone = f"+{phone}"

        if not phone:
            raise HTTPException(400, "Could not determine phone number")

        # Get final session string
        if session_bytes and not session_string:
            session_string = StringSession.save(client.session)

        # Disconnect client
        await client.disconnect()
        client = None

        # Create account
        account = await service.create_account(
            phone=phone,
            session_data=session_string.encode() if session_string else session_bytes,
        )

        # Update account with Telegram info
        account.telegram_id = me.id
        account.username = me.username
        account.first_name = me.first_name or ""
        account.last_name = me.last_name or ""
        account.is_premium = getattr(me, 'premium', False)

        # Assign proxy if provided
        if proxy_id:
            await service.assign_proxy(account.id, proxy_id)

        # Save updated account
        await service._account_repo.save(account)

        return AccountResponse.model_validate(account)

    except SessionPasswordNeededError:
        raise HTTPException(
            401,
            "Account requires 2FA password. Please provide twofa password in archive (Password2FA.txt)"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Account import failed", error=str(e))
        raise HTTPException(500, "Import failed due to an internal error")
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass
        if temp_dir:
            try:
                shutil.rmtree(temp_dir)
            except:
                pass


def _check_is_tdata(path: str) -> bool:
    """Check if the extracted folder contains tdata."""
    # Check direct tdata folder
    if os.path.isdir(os.path.join(path, "tdata")):
        return True

    # Check nested folders
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        if os.path.isdir(item_path):
            if os.path.isdir(os.path.join(item_path, "tdata")):
                return True
            if item == "tdata":
                return True

    return False


async def _convert_tdata_to_session(path: str) -> dict:
    """Convert tdata to Telethon session."""
    try:
        from opentele.api import API, UseCurrentSession
        from opentele.td import TDesktop
        from telethon.sessions import StringSession

        # Find tdata path
        tdata_path = None
        if os.path.isdir(os.path.join(path, "tdata")):
            tdata_path = os.path.join(path, "tdata")
        else:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    if item == "tdata":
                        tdata_path = item_path
                        break
                    if os.path.isdir(os.path.join(item_path, "tdata")):
                        tdata_path = os.path.join(item_path, "tdata")
                        break

        if not tdata_path:
            return {}

        # Check for 2FA password
        twofa = None
        for root, dirs, files in os.walk(path):
            for f in files:
                if f.lower() in ("password2fa.txt", "2fa.txt", "password.txt"):
                    with open(os.path.join(root, f), 'r', encoding='utf-8') as pf:
                        twofa = pf.read().strip()
                    break

        # Convert tdata
        tdesk = TDesktop(tdata_path)

        if not tdesk.isLoaded():
            return {}

        # Get phone from tdata
        phone = ""
        api = API.TelegramDesktop

        # Convert to Telethon
        client = await tdesk.ToTelethon(
            session="telethon_session",
            flag=UseCurrentSession,
            api=api,
        )

        # Export session string
        session_string = StringSession.save(client.session)

        return {
            "session_string": session_string,
            "phone": phone,
            "twofa": twofa,
        }

    except ImportError:
        # opentele not installed
        return {}
    except Exception:
        return {}


async def _parse_session_files(path: str) -> dict:
    """Parse Telethon session files from extracted archive."""
    import json

    session_file = None
    json_file = None
    twofa = None

    # Find session and json files
    for root, dirs, files in os.walk(path):
        for f in files:
            fpath = os.path.join(root, f)

            if f.endswith(".session"):
                session_file = fpath
            elif f.endswith(".json") and not f.startswith("_"):
                json_file = fpath
            elif f.lower() in ("password2fa.txt", "2fa.txt", "password.txt"):
                with open(fpath, 'r', encoding='utf-8') as pf:
                    twofa = pf.read().strip()

    if not session_file:
        return {}

    # Read session file
    with open(session_file, 'rb') as f:
        session_bytes = f.read()

    # Read json for additional info
    phone = ""
    if json_file:
        try:
            with open(json_file, 'r', encoding='utf-8') as jf:
                data = json.load(jf)
                phone = data.get("phone", "")
        except:
            pass

    return {
        "session_bytes": session_bytes,
        "phone": phone,
        "twofa": twofa,
    }


async def _convert_session_to_telethon_string(session_path: str) -> str:
    """Convert SQLite session file to StringSession."""
    try:
        from telethon.sessions import SQLiteSession, StringSession

        # This is a simplified conversion - may need adjustments
        return ""
    except:
        return ""
