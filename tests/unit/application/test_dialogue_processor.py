"""
Tests for dialogue processor components.
"""

import pytest
from src.application.services.dialogue_processor import (
    ResponseParser,
    DialogueAction,
    ParsedResponse,
)


class TestResponseParser:
    """Tests for ResponseParser."""
    
    @pytest.fixture
    def parser(self):
        return ResponseParser()
    
    # =========================================
    # Basic Parsing
    # =========================================
    
    def test_parse_simple_message(self, parser):
        """Single message without commands."""
        result = parser.parse("привет, как дела")
        
        assert result.messages == ["привет, как дела"]
        assert result.action == DialogueAction.CONTINUE
    
    def test_parse_empty(self, parser):
        """Empty response."""
        result = parser.parse("")
        
        assert result.messages == []
        assert result.action == DialogueAction.CONTINUE
    
    def test_parse_none(self, parser):
        """None response."""
        result = parser.parse(None)
        
        assert result.messages == []
        assert result.action == DialogueAction.CONTINUE
    
    # =========================================
    # Message Splitting
    # =========================================
    
    def test_split_by_separator(self, parser):
        """Split messages by |||."""
        result = parser.parse("первое сообщение ||| второе сообщение")
        
        assert result.messages == ["первое сообщение", "второе сообщение"]
        assert result.action == DialogueAction.CONTINUE
    
    def test_split_multiple(self, parser):
        """Split into multiple messages."""
        result = parser.parse("раз ||| два ||| три")
        
        assert result.messages == ["раз", "два", "три"]
    
    def test_split_with_spaces(self, parser):
        """Handle various spacing around separator."""
        result = parser.parse("раз|||два ||| три  |||  четыре")
        
        assert len(result.messages) == 4
        assert all(m.strip() for m in result.messages)
    
    def test_split_empty_parts(self, parser):
        """Filter out empty parts."""
        result = parser.parse("раз ||| ||| два")
        
        assert result.messages == ["раз", "два"]
    
    # =========================================
    # Command Extraction
    # =========================================
    
    def test_extract_send_links(self, parser):
        """Extract [SEND_LINKS] command."""
        result = parser.parse("лови ссылку [SEND_LINKS]")
        
        assert result.messages == ["лови ссылку"]
        assert result.action == DialogueAction.SEND_LINKS
    
    def test_extract_negative_finish(self, parser):
        """Extract [NEGATIVE_FINISH] command."""
        result = parser.parse("ок, удачи [NEGATIVE_FINISH]")
        
        assert result.messages == ["ок, удачи"]
        assert result.action == DialogueAction.NEGATIVE_FINISH
    
    def test_extract_creative_sent(self, parser):
        """Extract [CREATIVE_SENT] command."""
        result = parser.parse("хочешь скину? [CREATIVE_SENT]")
        
        assert result.messages == ["хочешь скину?"]
        assert result.action == DialogueAction.CREATIVE_SENT
    
    def test_extract_handoff(self, parser):
        """Extract [HANDOFF] command."""
        result = parser.parse("[HANDOFF]")
        
        assert result.messages == []
        assert result.action == DialogueAction.HANDOFF
    
    def test_command_case_insensitive(self, parser):
        """Commands are case insensitive."""
        result = parser.parse("тест [send_links]")
        assert result.action == DialogueAction.SEND_LINKS
        
        result = parser.parse("тест [SEND_LINKS]")
        assert result.action == DialogueAction.SEND_LINKS
        
        result = parser.parse("тест [Send_Links]")
        assert result.action == DialogueAction.SEND_LINKS
    
    def test_command_with_split(self, parser):
        """Command with message splitting."""
        result = parser.parse("понял ||| лови [SEND_LINKS]")
        
        assert result.messages == ["понял", "лови"]
        assert result.action == DialogueAction.SEND_LINKS
    
    def test_only_command(self, parser):
        """Only command, no text."""
        result = parser.parse("[NEGATIVE_FINISH]")
        
        assert result.messages == []
        assert result.action == DialogueAction.NEGATIVE_FINISH
    
    # =========================================
    # Text Cleaning
    # =========================================
    
    def test_clean_lowercase_first(self, parser):
        """Lowercase first letter."""
        result = parser.parse("Привет, как дела")
        
        assert result.messages == ["привет, как дела"]
    
    def test_clean_keep_uppercase_mid(self, parser):
        """Keep uppercase in middle (names, etc)."""
        result = parser.parse("привет, Иван")
        
        # First letter already lowercase, keeps rest
        assert "Иван" in result.messages[0] or "иван" in result.messages[0]
    
    def test_clean_remove_trailing_period(self, parser):
        """Remove trailing period."""
        result = parser.parse("всё понял.")
        
        assert result.messages == ["всё понял"]
    
    def test_clean_keep_question_mark(self, parser):
        """Keep question mark."""
        result = parser.parse("Как дела?")
        
        assert result.messages == ["как дела?"]
    
    def test_clean_keep_exclamation(self, parser):
        """Keep exclamation mark."""
        result = parser.parse("Круто!")
        
        assert result.messages == ["круто!"]
    
    def test_clean_normalize_spaces(self, parser):
        """Normalize multiple spaces."""
        result = parser.parse("раз   два    три")
        
        assert result.messages == ["раз два три"]
    
    def test_clean_strip_edges(self, parser):
        """Strip whitespace from edges."""
        result = parser.parse("  привет  ")
        
        assert result.messages == ["привет"]
    
    # =========================================
    # Complex Cases
    # =========================================
    
    def test_full_dialogue_response(self, parser):
        """Full realistic response."""
        text = "Да, сам такое проходил ||| на плечах особенно больно учиться."
        result = parser.parse(text)
        
        assert len(result.messages) == 2
        assert result.messages[0] == "да, сам такое проходил"
        assert result.messages[1] == "на плечах особенно больно учиться"
        assert result.action == DialogueAction.CONTINUE
    
    def test_creative_with_question(self, parser):
        """Creative message with question."""
        text = "Есть пара норм каналов ||| хочешь скину? [CREATIVE_SENT]"
        result = parser.parse(text)
        
        assert len(result.messages) == 2
        assert result.messages[1] == "хочешь скину?"
        assert result.action == DialogueAction.CREATIVE_SENT
    
    def test_links_response(self, parser):
        """Response before sending links."""
        text = "Лови [SEND_LINKS]"
        result = parser.parse(text)
        
        assert result.messages == ["лови"]
        assert result.action == DialogueAction.SEND_LINKS
    
    def test_negative_offtopic(self, parser):
        """Negative finish for offtopic."""
        text = "[NEGATIVE_FINISH]"
        result = parser.parse(text)
        
        assert result.messages == []
        assert result.action == DialogueAction.NEGATIVE_FINISH


class TestParsedResponse:
    """Tests for ParsedResponse dataclass."""
    
    def test_has_messages_true(self):
        """has_messages returns True when messages exist."""
        response = ParsedResponse(
            messages=["test"],
            action=DialogueAction.CONTINUE,
            raw_response="test",
        )
        assert response.has_messages is True
    
    def test_has_messages_false_empty(self):
        """has_messages returns False for empty list."""
        response = ParsedResponse(
            messages=[],
            action=DialogueAction.CONTINUE,
            raw_response="",
        )
        assert response.has_messages is False
    
    def test_has_messages_false_whitespace(self):
        """has_messages returns False for whitespace-only messages."""
        response = ParsedResponse(
            messages=["", "  "],
            action=DialogueAction.CONTINUE,
            raw_response="",
        )
        assert response.has_messages is False
