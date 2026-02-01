"""
Target file management utilities.

Handles:
- Moving processed targets to result files (success/failure/other)
- Removing processed targets from source file
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# Directory for target result files
TARGETS_DIR = Path("data/targets")


def ensure_targets_dir() -> Path:
    """Ensure targets directory exists."""
    TARGETS_DIR.mkdir(parents=True, exist_ok=True)
    return TARGETS_DIR


def get_result_file_path(campaign_id: str, result_type: str) -> Path:
    """
    Get path to result file.

    Args:
        campaign_id: Campaign UUID
        result_type: One of 'success', 'failure', 'other'

    Returns:
        Path to result file
    """
    ensure_targets_dir()
    return TARGETS_DIR / f"{campaign_id}_{result_type}.txt"


async def append_to_result_file(
    campaign_id: str,
    result_type: str,
    identifier: str,
    reason: Optional[str] = None,
) -> None:
    """
    Append target to result file.

    Args:
        campaign_id: Campaign UUID
        result_type: One of 'success', 'failure', 'other'
        identifier: Target identifier (username or telegram_id)
        reason: Optional reason (for failures)
    """
    file_path = get_result_file_path(campaign_id, result_type)

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    if reason:
        line = f"{identifier}\t{reason}\t{timestamp}\n"
    else:
        line = f"{identifier}\t{timestamp}\n"

    try:
        # Use aiofiles-like approach with asyncio.to_thread
        def write_sync():
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(line)

        await asyncio.to_thread(write_sync)

        logger.debug(
            "Target appended to result file",
            campaign_id=campaign_id,
            result_type=result_type,
            identifier=identifier,
        )

    except Exception as e:
        logger.error(
            "Failed to append to result file",
            campaign_id=campaign_id,
            result_type=result_type,
            error=str(e),
        )


async def remove_from_source_file(
    source_file_path: str,
    identifiers: list[str],
) -> int:
    """
    Remove processed identifiers from source file.

    Args:
        source_file_path: Path to source targets file
        identifiers: List of identifiers to remove

    Returns:
        Number of removed lines
    """
    if not source_file_path or not os.path.exists(source_file_path):
        logger.warning("Source file not found", path=source_file_path)
        return 0

    identifiers_set = set(i.lower().lstrip("@") for i in identifiers)
    removed_count = 0

    try:
        def process_sync():
            nonlocal removed_count

            # Read all lines
            with open(source_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Filter out processed targets
            remaining_lines = []
            for line in lines:
                line_stripped = line.strip().lower().lstrip("@")
                if line_stripped and line_stripped not in identifiers_set:
                    remaining_lines.append(line)
                elif line_stripped in identifiers_set:
                    removed_count += 1

            # Write back
            with open(source_file_path, "w", encoding="utf-8") as f:
                f.writelines(remaining_lines)

        await asyncio.to_thread(process_sync)

        logger.info(
            "Removed targets from source file",
            path=source_file_path,
            removed_count=removed_count,
        )

        return removed_count

    except Exception as e:
        logger.error(
            "Failed to remove from source file",
            path=source_file_path,
            error=str(e),
        )
        return 0


async def record_target_result(
    campaign_id: str,
    identifier: str,
    result: str,  # 'success', 'failure', 'other'
    reason: Optional[str] = None,
    source_file_path: Optional[str] = None,
) -> None:
    """
    Record target result and optionally remove from source file.

    Args:
        campaign_id: Campaign UUID
        identifier: Target identifier
        result: Result type ('success', 'failure', 'other')
        reason: Optional reason for failure
        source_file_path: Optional path to source file for cleanup
    """
    # Append to result file
    await append_to_result_file(campaign_id, result, identifier, reason)

    # Remove from source file if provided
    if source_file_path:
        await remove_from_source_file(source_file_path, [identifier])


async def get_result_stats(campaign_id: str) -> dict:
    """
    Get statistics from result files.

    Args:
        campaign_id: Campaign UUID

    Returns:
        Dict with counts for each result type
    """
    stats = {
        "success": 0,
        "failure": 0,
        "other": 0,
    }

    for result_type in stats.keys():
        file_path = get_result_file_path(campaign_id, result_type)
        if file_path.exists():
            try:
                def count_lines():
                    with open(file_path, "r", encoding="utf-8") as f:
                        return sum(1 for line in f if line.strip())

                stats[result_type] = await asyncio.to_thread(count_lines)
            except Exception:
                pass

    return stats
