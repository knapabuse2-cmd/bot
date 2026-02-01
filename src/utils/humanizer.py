"""
Humanizer utilities.

Provides human-like behavior patterns to avoid detection:
- Randomized delays between actions
- Typing simulation
- Activity scheduling
"""

import asyncio
import random
from datetime import datetime, time, timedelta
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class Humanizer:
    """
    Provides human-like behavior patterns.
    
    Helps avoid detection by introducing natural variations
    in timing and activity patterns.
    """
    
    def __init__(
        self,
        min_delay: float = 1.0,
        max_delay: float = 5.0,
        typing_speed_cpm: int = 300,  # Characters per minute
    ):
        """
        Initialize humanizer.
        
        Args:
            min_delay: Minimum delay between actions (seconds)
            max_delay: Maximum delay between actions (seconds)
            typing_speed_cpm: Simulated typing speed
        """
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.typing_speed_cpm = typing_speed_cpm
    
    def get_random_delay(
        self,
        min_override: Optional[float] = None,
        max_override: Optional[float] = None,
    ) -> float:
        """
        Get randomized delay.
        
        Uses gaussian distribution centered between min and max
        for more natural variation.
        
        Args:
            min_override: Override minimum delay
            max_override: Override maximum delay
            
        Returns:
            Random delay in seconds
        """
        min_d = min_override if min_override is not None else self.min_delay
        max_d = max_override if max_override is not None else self.max_delay
        
        # Use gaussian distribution for more natural timing
        mean = (min_d + max_d) / 2
        std_dev = (max_d - min_d) / 4
        
        delay = random.gauss(mean, std_dev)
        
        # Clamp to bounds
        return max(min_d, min(max_d, delay))
    
    async def random_delay(
        self,
        min_override: Optional[float] = None,
        max_override: Optional[float] = None,
    ) -> float:
        """
        Sleep for a random duration.
        
        Args:
            min_override: Override minimum delay
            max_override: Override maximum delay
            
        Returns:
            Actual delay used
        """
        delay = self.get_random_delay(min_override, max_override)
        await asyncio.sleep(delay)
        return delay
    
    def get_typing_duration(self, text: str) -> float:
        """
        Calculate realistic typing duration for text.
        
        Args:
            text: Text to "type"
            
        Returns:
            Duration in seconds
        """
        char_count = len(text)
        base_duration = (char_count / self.typing_speed_cpm) * 60
        
        # Add some randomness (±20%)
        variation = base_duration * 0.2
        duration = base_duration + random.uniform(-variation, variation)
        
        # Minimum 0.5 seconds, maximum 30 seconds
        return max(0.5, min(30.0, duration))
    
    async def simulate_typing(self, text: str) -> float:
        """
        Simulate typing delay for text.
        
        Args:
            text: Text being "typed"
            
        Returns:
            Actual duration
        """
        duration = self.get_typing_duration(text)
        await asyncio.sleep(duration)
        return duration
    
    def get_message_delay(self, is_first_message: bool = False) -> float:
        """
        Get appropriate delay before sending a message.
        
        Args:
            is_first_message: Whether this is the first message to user
            
        Returns:
            Delay in seconds
        """
        if is_first_message:
            # Longer delay for first contact (30-120 seconds)
            return self.get_random_delay(30, 120)
        else:
            # Normal delay for responses (5-30 seconds)
            return self.get_random_delay(5, 30)
    
    def get_response_delay(self, user_message_length: int) -> float:
        """
        Get delay before responding based on message complexity.
        
        Longer messages deserve more "thinking time".
        
        Args:
            user_message_length: Length of user's message
            
        Returns:
            Delay in seconds
        """
        # Base delay: 3-10 seconds
        base = self.get_random_delay(3, 10)
        
        # Add time based on message length (1 second per 50 chars)
        reading_time = (user_message_length / 50) * random.uniform(0.8, 1.2)
        
        # Cap at 30 seconds
        return min(30.0, base + reading_time)
    
    def is_within_schedule(
        self,
        start_time: time,
        end_time: time,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """
        Check if current time is within active schedule.
        
        Args:
            start_time: Schedule start time
            end_time: Schedule end time
            current_time: Time to check (defaults to now)
            
        Returns:
            True if within schedule
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        current = current_time.time()
        
        if start_time <= end_time:
            return start_time <= current <= end_time
        else:
            # Overnight schedule
            return current >= start_time or current <= end_time
    
    def get_next_active_time(
        self,
        start_time: time,
        end_time: time,
        current_time: Optional[datetime] = None,
    ) -> datetime:
        """
        Get next time that falls within schedule.
        
        Args:
            start_time: Schedule start time
            end_time: Schedule end time
            current_time: Reference time
            
        Returns:
            Next datetime within schedule
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        if self.is_within_schedule(start_time, end_time, current_time):
            return current_time
        
        # Calculate next start time
        next_start = datetime.combine(current_time.date(), start_time)
        
        if next_start <= current_time:
            # Start time already passed today, use tomorrow
            next_start += timedelta(days=1)
        
        # Add small random offset (1-15 minutes)
        offset = random.randint(60, 900)
        return next_start + timedelta(seconds=offset)
    
    def add_jitter(self, timestamp: datetime, max_jitter_seconds: int = 300) -> datetime:
        """
        Add random jitter to a timestamp.
        
        Args:
            timestamp: Original timestamp
            max_jitter_seconds: Maximum jitter in seconds
            
        Returns:
            Timestamp with jitter applied
        """
        jitter = random.randint(-max_jitter_seconds, max_jitter_seconds)
        return timestamp + timedelta(seconds=jitter)
    
    def humanize_text(self, text: str) -> str:
        """
        Make AI-generated text more human-like.

        - Remove AI special commands ([HANDOFF], [NEGATIVE_FINISH], etc.)
        - LIMIT TO MAX 1 QUESTION (critical!)
        - Lowercase first letter (80% chance)
        - Sometimes skip commas (30% chance per comma)
        - Add casual prefix sometimes
        - Remove excessive punctuation

        Args:
            text: AI-generated text

        Returns:
            More human-like text
        """
        import re

        if not text:
            return text

        result = text.strip()

        # Remove AI special commands that should never be sent to users
        # These are internal instructions that AI sometimes outputs
        result = re.sub(
            r'\[(SEND_LINKS|NEGATIVE_FINISH|CREATIVE_SENT|HANDOFF)\]',
            '',
            result,
            flags=re.IGNORECASE
        )

        # Also remove common AI artifacts
        result = re.sub(r'\[.*?_.*?\]', '', result)  # [ANY_COMMAND] pattern

        result = result.strip()
        
        # CRITICAL: Limit to max 1 question
        result = self._limit_questions(result)

        # NOTE: Removed random filler prefixes ("ага", "хз", "если честно", etc.)
        # They were added without context and sounded unnatural.
        # AI should generate natural reactions in its response if needed.

        # Lowercase first letter with 70% probability
        if result and result[0].isupper() and random.random() < 0.7:
            result = result[0].lower() + result[1:]
        
        # Skip some commas (25% chance each)
        new_result = []
        for i, char in enumerate(result):
            if char == ',' and random.random() < 0.25:
                continue
            new_result.append(char)
        result = ''.join(new_result)
        
        # Remove double spaces
        while '  ' in result:
            result = result.replace('  ', ' ')
        
        # Remove period at end (30% chance)
        if result.endswith('.') and random.random() < 0.3:
            result = result[:-1]
        
        # Remove exclamation marks
        result = result.replace('!', '.')
        
        # Simplify formal phrases
        replacements = [
            ('Понимаю,', 'понимаю'),
            ('Конечно,', 'ну'),
            ('Да,', 'да'),
            ('Нет,', 'нет'),
            ('Хорошо,', 'ок'),
            ('К сожалению,', 'блин'),
            ('На самом деле,', 'по факту'),
            ('Кстати,', 'кстати'),
            ('Действительно,', 'да'),
        ]
        for old, new in replacements:
            if result.startswith(old):
                result = new + result[len(old):]
        
        return result.strip()
    
    def _limit_questions(self, text: str) -> str:
        """
        Limit message to maximum ONE question.
        
        If AI generated multiple questions, keep only the first one.
        This prevents the annoying pattern of asking 2-3 questions at once.
        """
        import re
        
        if "?" not in text:
            return text
        
        # Split by sentence-ending punctuation while keeping the punctuation
        parts = re.split(r'([?.!])', text)
        sentences = []
        buf = ""
        
        for chunk in parts:
            if chunk in [".", "?", "!"]:
                buf += chunk
                sentences.append(buf.strip())
                buf = ""
            else:
                buf += chunk
        
        if buf.strip():
            sentences.append(buf.strip())
        
        if not sentences:
            return text
        
        # Keep only first question, all non-questions
        result = []
        question_count = 0
        
        for s in sentences:
            if "?" in s:
                if question_count == 0:
                    result.append(s)
                    question_count += 1
                # Skip additional questions
            else:
                result.append(s)
        
        final = " ".join(result).strip()
        return final if final else text


# Default humanizer instance
_humanizer: Optional[Humanizer] = None


def get_humanizer() -> Humanizer:
    """Get default humanizer instance."""
    global _humanizer
    
    if _humanizer is None:
        _humanizer = Humanizer()
    
    return _humanizer
