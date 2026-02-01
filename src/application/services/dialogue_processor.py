"""
Dialogue Processor.

Handles AI response generation and parsing with special commands.

Format:
- ||| = message separator (split into multiple messages)
- [SEND_LINKS] = send campaign links
- [NEGATIVE_FINISH] = end dialogue negatively
- [CREATIVE_SENT] = creative message sent, waiting for response
- [HANDOFF] = need human intervention
"""

import re
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

import structlog

from src.domain.entities import Dialogue, DialogueStatus, Message, MessageRole
from src.infrastructure.ai import OpenAIProvider

logger = structlog.get_logger(__name__)


class DialogueAction(str, Enum):
    """Actions parsed from AI response."""
    
    CONTINUE = "continue"           # Normal message, continue dialogue
    SEND_LINKS = "send_links"       # Send campaign links
    NEGATIVE_FINISH = "negative"    # End dialogue (rejection/off-topic)
    CREATIVE_SENT = "creative"      # Creative sent, mark state
    HANDOFF = "handoff"             # Need human review


@dataclass
class ParsedResponse:
    """
    Parsed AI response.
    
    Attributes:
        messages: List of messages to send (split by |||)
        action: Action to take after sending
        raw_response: Original AI response
    """
    messages: list[str]
    action: DialogueAction
    raw_response: str
    
    @property
    def has_messages(self) -> bool:
        return len(self.messages) > 0 and any(m.strip() for m in self.messages)


class ResponseParser:
    """
    Parses AI responses into messages and actions.
    
    Handles:
    - Message splitting by |||
    - Special command extraction
    - Text cleanup (lowercase, no periods)
    """
    
    # Special commands pattern
    COMMAND_PATTERN = re.compile(
        r'\[(SEND_LINKS|NEGATIVE_FINISH|CREATIVE_SENT|HANDOFF)\]',
        re.IGNORECASE
    )
    
    # Message separator
    SEPARATOR = '|||'
    
    def parse(self, response: str) -> ParsedResponse:
        """
        Parse AI response into structured format.
        
        Args:
            response: Raw AI response text
            
        Returns:
            ParsedResponse with messages and action
        """
        if not response:
            return ParsedResponse(
                messages=[],
                action=DialogueAction.CONTINUE,
                raw_response="",
            )
        
        # Extract action from commands
        action = self._extract_action(response)
        
        # Remove commands from text
        clean_text = self.COMMAND_PATTERN.sub('', response).strip()
        
        # Split by separator
        messages = self._split_messages(clean_text)
        
        # Clean each message
        messages = [self._clean_message(m) for m in messages]
        messages = [m for m in messages if m]  # Remove empty
        
        return ParsedResponse(
            messages=messages,
            action=action,
            raw_response=response,
        )
    
    def _extract_action(self, text: str) -> DialogueAction:
        """Extract action from special commands."""
        text_upper = text.upper()
        
        if '[SEND_LINKS]' in text_upper:
            return DialogueAction.SEND_LINKS
        elif '[NEGATIVE_FINISH]' in text_upper:
            return DialogueAction.NEGATIVE_FINISH
        elif '[CREATIVE_SENT]' in text_upper:
            return DialogueAction.CREATIVE_SENT
        elif '[HANDOFF]' in text_upper:
            return DialogueAction.HANDOFF
        else:
            return DialogueAction.CONTINUE
    
    def _split_messages(self, text: str) -> list[str]:
        """Split text by ||| separator."""
        if self.SEPARATOR not in text:
            return [text] if text.strip() else []
        
        parts = text.split(self.SEPARATOR)
        return [p.strip() for p in parts if p.strip()]
    
    def _clean_message(self, text: str) -> str:
        """
        Clean message text.
        
        - Lowercase (except proper nouns mid-sentence)
        - Remove trailing periods (keep ? !)
        - Normalize whitespace
        """
        if not text:
            return ""
        
        text = text.strip()
        
        # Lowercase first char if followed by lowercase
        if len(text) > 1 and text[0].isupper() and text[1].islower():
            text = text[0].lower() + text[1:]
        
        # Remove trailing period
        while text.endswith('.'):
            text = text[:-1].strip()
        
        # Normalize spaces
        text = re.sub(r'\s+', ' ', text)
        
        # Remove any remaining ||| that might be at edges
        text = text.strip('|').strip()
        
        return text


class DialogueProcessor:
    """
    Processes dialogue interactions.
    
    Responsibilities:
    - Generate AI responses with proper context
    - Parse responses into messages
    - Handle special actions
    - Manage dialogue state
    """
    
    def __init__(self, ai_provider: OpenAIProvider):
        self.ai_provider = ai_provider
        self.parser = ResponseParser()
    
    async def generate_response(
        self,
        dialogue: Dialogue,
        user_message: str,
        system_prompt: str,
        campaign_context: Optional[dict] = None,
    ) -> ParsedResponse:
        """
        Generate response to user message.
        
        Args:
            dialogue: Current dialogue with history
            user_message: User's message(s)
            system_prompt: Campaign system prompt
            campaign_context: Additional context (links, etc)
            
        Returns:
            ParsedResponse with messages and action
        """
        campaign_context = campaign_context or {}
        
        # Build conversation history
        history = self._build_history(dialogue)
        
        # Add current message
        history.append({"role": "user", "content": user_message})
        
        # Add context about dialogue state
        enhanced_prompt = self._enhance_prompt(
            system_prompt,
            dialogue,
            campaign_context,
        )
        
        try:
            response = await self.ai_provider.generate(
                messages=history,
                system_prompt=enhanced_prompt,
                temperature=campaign_context.get("temperature", 0.8),
                max_tokens=campaign_context.get("max_tokens", 300),
            )
            
            # Parse response
            parsed = self.parser.parse(response.content)
            
            logger.debug(
                "Response generated",
                messages_count=len(parsed.messages),
                action=parsed.action.value,
            )
            
            return parsed
            
        except Exception as e:
            logger.error("Response generation failed", error=str(e))
            # Return safe fallback
            return ParsedResponse(
                messages=["хм, не понял"],
                action=DialogueAction.CONTINUE,
                raw_response="",
            )
    
    async def generate_first_message(
        self,
        system_prompt: str,
        campaign_context: Optional[dict] = None,
    ) -> ParsedResponse:
        """
        Generate first outreach message.
        
        Args:
            system_prompt: Campaign system prompt
            campaign_context: Additional context
            
        Returns:
            ParsedResponse with first message(s)
        """
        campaign_context = campaign_context or {}
        
        # Use dedicated first message prompt
        from src.application.prompts import get_first_message_prompt
        first_msg_prompt = get_first_message_prompt()

        try:
            response = await self.ai_provider.generate(
                messages=[{"role": "user", "content": "начни диалог"}],
                system_prompt=first_msg_prompt,
                temperature=0.9,
                max_tokens=100,
            )
            
            return self.parser.parse(response.content)
            
        except Exception as e:
            logger.error("First message generation failed", error=str(e))
            # Fallback
            return ParsedResponse(
                messages=["ты на фьючах торгуешь или спот?"],
                action=DialogueAction.CONTINUE,
                raw_response="",
            )
    
    def _build_history(self, dialogue: Dialogue) -> list[dict]:
        """Build conversation history for AI."""
        history = []
        
        for msg in dialogue.messages:
            role = "assistant" if msg.role == MessageRole.ACCOUNT else "user"
            history.append({
                "role": role,
                "content": msg.content,
            })
        
        return history
    
    def _enhance_prompt(
        self,
        base_prompt: str,
        dialogue: Dialogue,
        context: dict,
    ) -> str:
        """
        Enhance prompt with dialogue state.
        
        Adds:
        - Message count info
        - Whether links were sent
        - Current goal status
        """
        parts = [base_prompt]
        
        # Dialogue state
        msg_count = len(dialogue.messages)
        
        state_info = f"""
---
СОСТОЯНИЕ ДИАЛОГА:
- Сообщений в диалоге: {msg_count}
- Ссылки отправлены: {"да" if dialogue.goal_message_sent else "нет"}
"""
        
        if dialogue.goal_message_sent:
            state_info += "- Уже отправил ссылки, не повторяй [SEND_LINKS]\n"
        
        parts.append(state_info)
        
        # Links info if available
        if context.get("links"):
            links = context["links"]
            parts.append(f"""
ССЫЛКИ ДЛЯ ОТПРАВКИ (когда [SEND_LINKS]):
{links}
""")
        
        return "\n".join(parts)
    
    def should_send_links(self, parsed: ParsedResponse) -> bool:
        """Check if should send campaign links."""
        return parsed.action == DialogueAction.SEND_LINKS
    
    def should_end_dialogue(self, parsed: ParsedResponse) -> bool:
        """Check if dialogue should be ended."""
        return parsed.action == DialogueAction.NEGATIVE_FINISH
    
    def needs_handoff(self, parsed: ParsedResponse) -> bool:
        """Check if needs human intervention."""
        return parsed.action == DialogueAction.HANDOFF


class MessageBatcher:
    """
    Collects multiple user messages before responding.
    
    Waits for user to finish typing (3 sec pause).
    """
    
    WAIT_SECONDS = 3.0
    MAX_WAIT_SECONDS = 15.0
    
    def __init__(self):
        self._buffers: dict[str, dict] = {}
        self._timers: dict[str, asyncio.Task] = {}
    
    def _key(self, account_id: UUID, user_id: int) -> str:
        return f"{account_id}:{user_id}"
    
    async def add_message(
        self,
        account_id: UUID,
        user_id: int,
        text: str,
        message_id: int,
        on_ready: callable,
    ) -> None:
        """
        Add message to buffer.
        
        Calls on_ready when user stops typing.
        """
        key = self._key(account_id, user_id)
        
        # Init buffer
        if key not in self._buffers:
            self._buffers[key] = {
                "messages": [],
                "message_ids": [],
                "first_at": datetime.utcnow(),
                "last_at": datetime.utcnow(),
                "callback": on_ready,
            }
        
        buf = self._buffers[key]
        buf["messages"].append(text)
        buf["message_ids"].append(message_id)
        buf["last_at"] = datetime.utcnow()
        buf["callback"] = on_ready
        
        # Cancel existing timer
        if key in self._timers and not self._timers[key].done():
            self._timers[key].cancel()
        
        # Start new timer
        self._timers[key] = asyncio.create_task(
            self._wait_and_process(key)
        )
    
    async def _wait_and_process(self, key: str) -> None:
        """Wait for pause, then process."""
        try:
            await asyncio.sleep(self.WAIT_SECONDS)
            
            buf = self._buffers.get(key)
            if not buf:
                return
            
            # Check if more messages came
            while True:
                elapsed = (datetime.utcnow() - buf["last_at"]).total_seconds()
                if elapsed >= self.WAIT_SECONDS:
                    break
                
                # Check max wait
                total = (datetime.utcnow() - buf["first_at"]).total_seconds()
                if total >= self.MAX_WAIT_SECONDS:
                    break
                
                await asyncio.sleep(self.WAIT_SECONDS - elapsed + 0.1)
            
            # Process
            combined = "\n".join(buf["messages"])
            msg_ids = buf["message_ids"].copy()
            callback = buf["callback"]
            
            # Clear buffer
            del self._buffers[key]
            
            # Call handler
            if callback:
                await callback(combined, msg_ids)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Batcher error", error=str(e))
    
    def cancel_all(self) -> None:
        """Cancel all pending."""
        for task in self._timers.values():
            if not task.done():
                task.cancel()
        self._timers.clear()
        self._buffers.clear()


class TypingSimulator:
    """Simulates human reading/typing times."""
    
    # Reading: ~15 chars per second
    READING_CPS = 15
    
    # Typing: ~200-300 chars per minute
    TYPING_CPM = 250
    
    def get_reading_time(self, text: str) -> float:
        """Time to 'read' incoming message."""
        import random
        
        chars = len(text)
        base = chars / self.READING_CPS
        
        # Add thinking time
        thinking = random.uniform(0.5, 2.0)
        
        # Randomize
        result = base * random.uniform(0.8, 1.2) + thinking
        
        # Clamp
        return max(1.0, min(result, 8.0))
    
    def get_typing_time(self, text: str) -> float:
        """Time to 'type' outgoing message."""
        import random
        
        chars = len(text)
        base = (chars / self.TYPING_CPM) * 60
        
        # Randomize
        result = base * random.uniform(0.8, 1.3)
        
        # Clamp
        return max(1.0, min(result, 12.0))
    
    def get_pause_between(self) -> float:
        """Pause between multiple messages."""
        import random
        return random.uniform(0.8, 2.0)
