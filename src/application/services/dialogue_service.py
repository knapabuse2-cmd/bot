"""
Dialogue service.

Handles the core dialogue logic including:
- Starting conversations
- Processing incoming messages
- Generating AI responses
- Managing dialogue state
"""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

import structlog

from src.application.interfaces.repository import (
    CampaignRepository,
    DialogueRepository,
    UserTargetRepository,
)
from src.domain.entities import (
    Dialogue,
    DialogueStatus,
    Message,
    MessageRole,
    TargetStatus,
)
from src.domain.exceptions import (
    DialogueAlreadyExistsError,
    DialogueNotFoundError,
)
from src.infrastructure.ai import OpenAIProvider
from src.utils.humanizer import Humanizer
from src.utils.target_files import record_target_result

logger = structlog.get_logger(__name__)


class DialogueService:
    """
    Service for managing AI-powered dialogues.
    
    Handles the full lifecycle of conversations:
    - Initiating contact with targets
    - Processing incoming messages
    - Generating contextual AI responses
    - Tracking progress toward campaign goals
    """
    
    def __init__(
        self,
        dialogue_repo: DialogueRepository,
        campaign_repo: CampaignRepository,
        target_repo: UserTargetRepository,
        ai_provider: OpenAIProvider,
        humanizer: Optional[Humanizer] = None,
    ):
        self.dialogue_repo = dialogue_repo
        self.campaign_repo = campaign_repo
        self.target_repo = target_repo
        self.ai_provider = ai_provider
        self.humanizer = humanizer or Humanizer()
    
    async def start_dialogue(
        self,
        account_id: UUID,
        campaign_id: UUID,
        target_id: UUID,
        telegram_user_id: Optional[int] = None,
        telegram_username: Optional[str] = None,
    ) -> tuple[Dialogue, str]:
        """
        Start a new dialogue with a target user.
        
        Args:
            account_id: Worker account UUID
            campaign_id: Campaign UUID
            target_id: Target user UUID
            telegram_user_id: Telegram user ID (optional, resolved later)
            telegram_username: Telegram username
            
        Returns:
            Tuple of (Dialogue, first_message_text)
            
        Raises:
            DialogueAlreadyExistsError: If dialogue already exists
        """
        # Check for existing dialogue by target_id
        existing = await self.dialogue_repo.get_by_target(target_id)
        if existing and existing.status not in (
            DialogueStatus.COMPLETED,
            DialogueStatus.FAILED,
            DialogueStatus.EXPIRED,
        ):
            raise DialogueAlreadyExistsError(str(account_id), str(target_id))
        
        # Get campaign for prompt
        campaign = await self.campaign_repo.get_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        
        # Generate first message
        first_message = await self._generate_first_message(campaign)
        
        # Create dialogue
        dialogue = Dialogue(
            account_id=account_id,
            campaign_id=campaign_id,
            target_user_id=target_id,
            telegram_user_id=telegram_user_id or 0,  # Will be updated after send
            telegram_username=telegram_username,
            status=DialogueStatus.INITIATED,
        )
        
        # Add first message
        message = dialogue.add_message(
            message_id=uuid4(),
            role=MessageRole.ACCOUNT,
            content=first_message,
            ai_generated=True,
        )
        
        # Schedule next action (follow-up if no response)
        dialogue.next_action_at = datetime.utcnow() + timedelta(hours=24)
        
        saved = await self.dialogue_repo.save(dialogue)
        
        # Update target status
        target = await self.target_repo.get_by_id(target_id)
        if target:
            target.mark_contacted(dialogue.id)
            await self.target_repo.save(target)
        
        # Update campaign stats
        await self.campaign_repo.update_stats(
            campaign_id,
            contacted=1,
            messages_sent=1,
        )
        
        logger.info(
            "Dialogue started",
            dialogue_id=str(saved.id),
            account_id=str(account_id),
            target_user_id=telegram_user_id,
        )
        
        return saved, first_message
    
    async def update_dialogue(self, dialogue: Dialogue) -> Dialogue:
        """
        Update an existing dialogue.
        
        Args:
            dialogue: Dialogue entity to update
            
        Returns:
            Updated dialogue
        """
        return await self.dialogue_repo.save(dialogue)
    
    async def process_incoming_message(
        self,
        account_id: UUID,
        telegram_user_id: int,
        text: str,
        telegram_message_id: Optional[int] = None,
        telegram_username: Optional[str] = None,
    ) -> Optional[tuple[Dialogue, str]]:
        """
        Process an incoming message from a user.
        
        Logic (based on old working project):
        1. Track interest score from user messages
        2. Check for explicit link request → send link immediately
        3. Check for soft interest + enough messages → send link
        4. Otherwise → AI response
        
        Args:
            account_id: Worker account UUID
            telegram_user_id: Sender Telegram ID
            text: Message text
            telegram_message_id: Telegram message ID
            telegram_username: Sender username
            
        Returns:
            Tuple of (Dialogue, response_text) or None if no dialogue
        """
        # Find existing dialogue
        dialogue = await self.dialogue_repo.get_by_account_and_user(
            account_id, telegram_user_id, telegram_username
        )
        
        if not dialogue:
            logger.debug(
                "No dialogue found for incoming message",
                account_id=str(account_id),
                telegram_user_id=telegram_user_id,
            )
            return None
        
        # Skip if dialogue is finished
        if dialogue.status in (
            DialogueStatus.COMPLETED,
            DialogueStatus.FAILED,
            DialogueStatus.EXPIRED,
        ):
            return None

        # Check for sticker/media spam - if user sends 3+ non-text messages in a row, ignore
        if self._is_media_spam(dialogue, text):
            logger.info(
                "Media spam detected, ignoring dialogue",
                dialogue_id=str(dialogue.id),
                telegram_user_id=telegram_user_id,
            )
            # Mark dialogue as failed due to spam
            dialogue.mark_failed("media_spam")
            await self.dialogue_repo.save(dialogue)

            # Update target
            target = await self.target_repo.get_by_id(dialogue.target_user_id)
            if target:
                target.mark_failed("media_spam")
                await self.target_repo.save(target)

            await self.campaign_repo.update_stats(
                dialogue.campaign_id,
                failed=1,
            )
            return None

        # Add user message
        dialogue.add_message(
            message_id=uuid4(),
            role=MessageRole.USER,
            content=text,
            telegram_message_id=telegram_message_id,
        )
        
        # Count messages
        our_messages = len([m for m in dialogue.messages if m.role == MessageRole.ACCOUNT])
        user_messages = len([m for m in dialogue.messages if m.role == MessageRole.USER])
        
        # Update interest score
        interest_delta = self._calculate_interest_delta(text)
        dialogue.interest_score = (dialogue.interest_score or 0) + interest_delta
        
        logger.info(
            "Processing message",
            dialogue_id=str(dialogue.id),
            our_messages=our_messages,
            user_messages=user_messages,
            interest_score=dialogue.interest_score,
            text_preview=text[:50],
        )

        # Check for explicit rejection ONLY AFTER we offered the link
        # Before that, user might say something that sounds like rejection but isn't
        if dialogue.goal_message_sent and self._is_rejection(text):
            logger.info(
                "User rejected offer after link was sent",
                dialogue_id=str(dialogue.id),
                text_preview=text[:50],
            )
            # Generate polite response and end dialogue
            response_text = self._get_rejection_response()
            dialogue.add_message(
                message_id=uuid4(),
                role=MessageRole.ACCOUNT,
                content=response_text,
                ai_generated=False,
                tokens_used=0,
            )
            dialogue.mark_failed("user_rejected")
            saved = await self.dialogue_repo.save(dialogue)

            # Update target
            target = await self.target_repo.get_by_id(dialogue.target_user_id)
            if target:
                target.mark_failed("user_rejected")
                await self.target_repo.save(target)

            await self.campaign_repo.update_stats(
                dialogue.campaign_id,
                failed=1,
                messages_sent=1,
            )

            return saved, response_text

        # Update status on first response
        if dialogue.status == DialogueStatus.INITIATED:
            dialogue.status = DialogueStatus.ACTIVE
            await self.campaign_repo.update_stats(
                dialogue.campaign_id,
                responded=1,
            )
            target = await self.target_repo.get_by_id(dialogue.target_user_id)
            if target:
                target.mark_in_progress()
                await self.target_repo.save(target)
        
        # Get campaign for link
        campaign = await self.campaign_repo.get_by_id(dialogue.campaign_id)
        
        # Check for EXPLICIT link request (like linker.py is_link_request)
        if self._is_explicit_link_request(text) and not dialogue.goal_message_sent:
            logger.info("Explicit link request detected", text=text[:30])
            response_text = await self._send_link_response(dialogue, campaign)
            tokens_used = 0
        # Check if user said short positive after we mentioned channel
        elif self._is_consent_after_channel_mention(dialogue, text) and not dialogue.goal_message_sent:
            logger.info("Consent after channel mention", text=text[:30])
            response_text = await self._send_link_response(dialogue, campaign)
            tokens_used = 0
        # Check for SOFT interest + enough messages (like linker.py user_interested)
        elif (self._is_soft_interest(text) and 
              not dialogue.goal_message_sent and
              user_messages >= 3 and 
              (dialogue.interest_score or 0) >= 1):
            logger.info("Soft interest + conditions met", text=text[:30], interest=dialogue.interest_score)
            response_text = await self._send_link_response(dialogue, campaign)
            tokens_used = 0
        # SECOND MESSAGE - template to continue conversation naturally
        elif our_messages == 1:
            response_text = self._get_second_message()
            tokens_used = 0
            logger.info("Sending second message template")
        else:
            # Regular AI response
            response = await self._generate_response(dialogue, text)
            response_text = response.content
            tokens_used = response.total_tokens
            
            # Humanize AI-generated text
            response_text = self.humanizer.humanize_text(response_text)
        
        # Add response message
        dialogue.add_message(
            message_id=uuid4(),
            role=MessageRole.ACCOUNT,
            content=response_text,
            ai_generated=True,
            tokens_used=tokens_used,
        )
        
        # Check goal progress
        await self._check_goal_progress(dialogue)
        
        # Update next action time
        dialogue.next_action_at = datetime.utcnow() + timedelta(hours=24)
        
        saved = await self.dialogue_repo.save(dialogue)
        
        # Update campaign stats
        await self.campaign_repo.update_stats(
            dialogue.campaign_id,
            messages_sent=1,
            tokens_used=tokens_used,
        )
        
        logger.info(
            "Message processed",
            dialogue_id=str(dialogue.id),
            response_len=len(response_text),
            goal_sent=dialogue.goal_message_sent,
        )
        
        return saved, response_text
    
    def _calculate_interest_delta(self, text: str) -> int:
        """
        Calculate interest score delta from user message.
        
        Based on history.py _interest_delta from old project.
        """
        t = text.lower()
        delta = 0
        
        # Questions about trading approach
        if any(w in t for w in ["как торгуешь", "как ты торгуешь", "стратег", "как заходишь"]):
            delta += 2
        
        # Mentions of signals/entries
        if any(w in t for w in ["сигнал", "сигналы", "точки входа", "входы"]):
            delta += 3
        
        # Direct mention of channel/chat
        if any(w in t for w in ["канал", "чат", "телег"]):
            delta += 4
        
        # Positive expressions
        if any(w in t for w in ["интересно", "круто", "норм идея", "норм тема"]):
            delta += 1
        
        return min(20, delta)  # Cap at 20
    
    def _is_explicit_link_request(self, text: str) -> bool:
        """
        Check if user explicitly asked for link/channel.
        
        Based on linker.py is_link_request from old project.
        """
        t = text.lower()
        
        triggers = [
            "ссылк", "линк", "link", "url",
            "кинь канал", "дай канал", "скинь канал",
            "кинь чат", "дай чат", "скинь чат",
            "дай свой канал", "кинь свой канал",
            "кинь свой чат", "дай свой чат",
            "твоя телега", "твой канал", "твой чат",
            "телегу", "телега",
            "скинь ссылку", "дай ссылку", "кинь ссылку",
        ]
        
        return any(tr in t for tr in triggers)
    
    def _is_soft_interest(self, text: str) -> bool:
        """
        Check if user expressed soft interest (not explicit request).

        Based on linker.py user_interested from old project.
        More aggressive matching - if they say "давай" after we mentioned channel, that's interest.
        """
        t = text.lower().strip()

        # First check if this is actually a rejection
        if self._is_rejection(text):
            return False

        # Short positive responses = interest
        short_positives = ["давай", "да", "ок", "окей", "ага", "угу", "го", "можно", "хочу"]
        if t in short_positives:
            return True

        # Longer phrases with interest
        keywords = [
            "давай ссылку",
            "давай канал",
            "интересно",
            "было бы интересно",
            "хочу посмотреть",
            "хочу глянуть",
            "гляну",
            "посмотрю",
            "покажи",
            "скинь",
        ]

        return any(key in t for key in keywords)

    def _is_media_spam(self, dialogue: Dialogue, current_text: str) -> bool:
        """
        Check if user is spamming stickers/media.

        Returns True if user sent 3+ stickers/media in a row (including current message).
        """
        # Media markers from telegram client
        media_markers = ["[стикер", "[фото]", "[видео]", "[голосовое", "[видеосообщение]", "[гифка]", "[файл]"]

        def is_media_message(text: str) -> bool:
            return any(marker in text.lower() for marker in media_markers)

        # Check if current message is media
        if not is_media_message(current_text):
            return False

        # Count consecutive media messages from user (from the end)
        consecutive_media = 1  # Current message is media

        # Get last user messages (reverse order)
        user_messages = [m for m in dialogue.messages if m.role == MessageRole.USER]

        for msg in reversed(user_messages):
            if is_media_message(msg.content):
                consecutive_media += 1
            else:
                # Found a non-media message, stop counting
                break

        # If 3+ consecutive media messages, it's spam
        return consecutive_media >= 3

    def _is_rejection(self, text: str) -> bool:
        """
        Check if user explicitly rejected/declined the offer.

        Returns True if user said they are NOT interested.
        """
        t = text.lower().strip()

        # Exact match rejections (must match whole message)
        exact_rejections = [
            "нее", "неа", "не-а", "пас", "пасс", "не", "нет",
        ]

        # Check exact matches for short responses
        if t in exact_rejections:
            logger.debug("Rejection detected: exact match", text=t)
            return True

        # Phrase rejections (can be part of message)
        phrase_rejections = [
            "не надо",
            "не нужно",
            "не интересно",
            "неинтересно",
            "не интересует",
            "не очень интересно",
            "не особо интересно",
            "не очень",
            "не особо",
            "мне не интересно",
            "мне неинтересно",
            "мне не очень интересно",
            "не хочу",
            "нет спасибо",
            "нет, спасибо",
            "спасибо не надо",
            "спасибо, не надо",
            "спасибо не нужно",
            "спасибо, не нужно",
            "не скидывай",
            "не кидай",
            "не присылай",
            "не надо ссылку",
            "без ссылок",
            "ссылки не надо",
            "ссылку не надо",
            "ссылка не нужна",
            "канал не надо",
            "канал не нужен",
            "не сейчас",
            "потом как-нибудь",
            "как-нибудь потом",
            "может потом",
            "в другой раз",
            "не, спасибо",
            "да не",
            "да нет",
            "не, не надо",
            "откажусь",
            "воздержусь",
            "не стоит",
            "не буду",
            "не, не буду",
            "лучше не надо",
            "я пас",
            "мне норм",
            "мне и так норм",
            "без меня",
        ]

        # Check if rejection phrase is in the text
        for rej in phrase_rejections:
            if rej in t:
                logger.debug("Rejection detected: phrase in text", text=t, phrase=rej)
                return True

        # Pattern: starts with "не " or "нет " - but only for short messages
        # to avoid false positives like questions
        if len(t) < 30 and (t.startswith("не ") or t.startswith("нет ") or t.startswith("нет,")):
            logger.debug("Rejection detected: starts with не/нет", text=t)
            return True

        return False
    
    def _is_consent_after_channel_mention(self, dialogue: Dialogue, text: str) -> bool:
        """
        Check if user gave short positive response after we mentioned channel.
        
        This catches cases like:
        - Us: "у меня есть канал, если интересно"
        - User: "давай" / "да" / "ок"
        """
        t = text.lower().strip()
        
        # Must be short positive response
        short_positives = ["давай", "да", "ок", "окей", "ага", "угу", "го", "можно", 
                          "хочу", "интересно", "гляну", "посмотрю", "покажи"]
        
        is_short_positive = t in short_positives or any(t.startswith(p) for p in short_positives[:5])
        
        if not is_short_positive:
            return False
        
        # Check if our last message mentioned channel
        last_our_msg = None
        for msg in reversed(dialogue.messages):
            if msg.role == MessageRole.ACCOUNT:
                last_our_msg = msg
                break
        
        if not last_our_msg:
            return False
        
        channel_words = ["канал", "чат", "телег", "ссылк", "скину", "кину", "интересно"]
        last_text = last_our_msg.content.lower()
        
        return any(word in last_text for word in channel_words)
    
    async def _send_link_response(self, dialogue: Dialogue, campaign) -> str:
        """
        Send link to user with proper formatting.
        
        Based on linker.py send_link_to from old project.
        """
        import random
        
        # Mark goal as sent
        dialogue.goal_message_sent = True
        dialogue.goal_message_sent_at = datetime.utcnow()
        
        # Check if already sent before
        if dialogue.link_sent_count and dialogue.link_sent_count > 0:
            intro = "я же уже кидал, но вот еще раз, если потерял)"
        else:
            intros = [
                "окей, ща кину",
                "да без проблем",
                "ага, щас закину",
                "да, держи",
                "легко",
            ]
            intro = random.choice(intros)
        
        dialogue.link_sent_count = (dialogue.link_sent_count or 0) + 1
        
        link = campaign.goal.target_url or ""
        
        post_messages = [
            "там без всяких VIP и марафонов. просто ребята делятся сетапами и рыночными идеями",
            "там спокойно, без продаж и навязчивых VIP. чисто обсуждаем уровни и движ по рынку",
            "канал обычный, без марафонов и буллшита — просто трейдеры, которые делятся входами",
            "там нет платных подписок. просто реальный живой разбор рынка",
            "там чистый формат — сетапы, уровни, идеи. никаких VIP и разводов",
        ]
        post = random.choice(post_messages)
        
        # Combine: intro + link + explanation
        return f"{intro}\n\n{link}\n\n{post}"
    
    async def _generate_first_message(self, campaign) -> str:
        """
        Generate the first contact message - varied greeting.

        Anti-detection: Use diverse greetings to avoid pattern recognition.
        """
        import random

        # Large pool of natural Russian greetings with variations
        greetings = [
            # Basic greetings
            "привет",
            "прив",
            "приветт",
            "хай",
            "хей",
            "здарова",
            "здорова",
            "здарово",
            "здоров",
            "ку",
            "йо",
            "ооо привет",
            "о привет",
            "эй",

            # With emoji (occasional)
            "привет 👋",
            "хай ✌️",
            "прив)",

            # Longer casual greetings
            "привет привет",
            "ну привет",
            "а привет",
            "прив прив",

            # Time-based (can add logic later)
            "добрый день",
            "доброго времени",
        ]

        # Weight towards simpler greetings
        weights = [
            10, 8, 5, 8, 6, 7, 6, 5, 4, 6, 4, 3, 2, 2,  # Basic
            3, 2, 4,  # With emoji
            3, 2, 2, 2,  # Longer
            2, 1,  # Formal
        ]

        return random.choices(greetings, weights=weights, k=1)[0]
    
    def _get_second_message(self) -> str:
        """
        Get scripted second message - natural continuation of conversation.

        Anti-detection: Large pool of varied openers to avoid pattern recognition.
        Should be conversational, not pushy about signals/channels.
        """
        import random

        # Expanded pool of natural follow-ups
        openers = [
            # Experience questions
            "а давно в крипте вообще?",
            "давно торгуешь?",
            "сколько уже в теме?",
            "давно в рынке?",
            "а когда начал заниматься криптой?",

            # How's it going
            "ну и как оно, норм заходит?",
            "как вообще идёт?",
            "ну как движуха?",
            "как успехи?",
            "норм получается?",

            # Trading style
            "сам больше на споте или фьючи тоже?",
            "больше спот или деривативы?",
            "споты или фьючи предпочитаешь?",
            "на фьючах торгуешь?",

            # Coins
            "а какие монеты сейчас смотришь?",
            "что сейчас держишь?",
            "в какие монеты веришь?",
            "какие активы в портфеле?",
            "что в закупке сейчас?",

            # BTC focus
            "биток держишь или больше альты?",
            "больше в битке сидишь?",
            "как по битку настроен?",

            # Exchange
            "на какой бирже в основном?",
            "бинанс или байбит?",
            "какую биржу юзаешь?",
            "где торгуешь обычно?",

            # General
            "чем вообще занимаешься в крипте?",
            "трейдишь или ходлишь?",
            "на долгосрок или активно торгуешь?",
            "сейчас активно в рынке?",
        ]
        return random.choice(openers)

    def _get_rejection_response(self) -> str:
        """
        Get polite response when user declines the offer.

        Anti-detection: Varied polite endings to avoid pattern recognition.
        """
        import random

        responses = [
            # Short acknowledgments
            "окей, без проблем",
            "понял, всё норм",
            "ок, без вопросов",
            "ок понял",
            "лады",
            "ну ок",
            "понял",
            "ясно",
            "хорошо",
            "окей",

            # With wishes
            "лады, удачи тебе",
            "окей, понял тебя",
            "хорошо, удачи в торговле",
            "понял, успехов",
            "ок, удачи",
            "понял тебя, удачи",
            "ну лады, удачи",
            "ок, успехов в торговле",

            # Friendly
            "да без проблем",
            "норм, понял",
            "всё понятно",
            "принял",
            "ясно, ну удачи тогда",
            "понял тебя, если что пиши",
        ]
        return random.choice(responses)
    
    def _get_goal_intro_message(self, links_count: int = 1) -> str:
        """
        Get intro message before sending goal links.

        Anti-detection: Varied intro messages to avoid pattern recognition.
        """
        import random

        if links_count == 1:
            intros = [
                "скидываю ссылку на канал — лично проверял, все достойно. реально отличается от того хлама, что обычно попадается",
                "вот ссылка на канал, сам подписан — годный контент, не кидалово",
                "держи ссылку, лично смотрел — норм канал, не скам",
                "скину ссылку на канал, проверенный — сам там сижу",
                "вот канал, смотрю его давно — реально годнота",
                "кидаю ссылку, канал проверенный мной лично",
                "скидываю канал — сам подписан, контент реально норм",
                "вот ссылка на канал — там всё по делу, не вода",
            ]
        else:
            intros = [
                f"скидываю ссылки на эти {links_count} канала — лично проверял, все достойно",
                f"вот {links_count} канала, которые сам смотрю — годный контент",
                f"держи ссылки на {links_count} канала, проверенные — норм инфа",
                f"кидаю {links_count} канала — сам на них подписан",
                f"вот {links_count} канала, которые реально стоит посмотреть",
            ]

        return random.choice(intros)
    
    def _should_send_links_now(self, dialogue: Dialogue, user_message: str) -> bool:
        """
        DEPRECATED - now using _is_explicit_link_request and _is_soft_interest.
        """
        return False
    
    async def _generate_response(self, dialogue: Dialogue, user_message: str):
        """Generate AI response for dialogue using prompt from old working project."""
        campaign = await self.campaign_repo.get_by_id(dialogue.campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {dialogue.campaign_id} not found")
        
        # Build system prompt - based on prompts.py from old project
        system_prompt = campaign.get_system_prompt() or self._get_default_system_prompt()
        
        # Add critical rules that were in old project
        system_prompt += """

КРИТИЧЕСКИЕ ПРАВИЛА:

ВОПРОСЫ:
- МАКСИМУМ один вопрос в одном сообщении. Лучше вообще без вопросов.
- Не задавай вопрос в каждом сообщении. В среднем — 1 вопрос на 4 сообщения.
- НЕ ПЕРЕСПРАШИВАЙ то, на что человек уже ответил.
- Если он сказал «фьючи» - НЕ спрашивай снова «ты фьючи торгуешь?».
- Если он ответил коротко («норм», «потихоньку», «да», «хуево») — это полный ответ. Развивай тему, НЕ переспрашивай.

СТИЛЬ:
- 1–2 предложения максимум. Не больше.
- Никаких списков, буллетов, структуры.
- Сленг норм: «по факту», «сливался», «просадка», «норм», «хз».
- БЕЗ смайликов и эмодзи.
- Без заглавных букв в начале.

КАНАЛ:
- У тебя есть свой канал по крипте. Не придумывай название.
- Можно упомянуть: "у меня в канале такое было", "я у себя уровни кидаю".
- Ссылку НЕ отправляй сам — только если спросят, скажи "могу скинуть".

ТАБУ:
- Не говори что ты бот/ИИ/ассистент.
- Минимум теории, максимум живого опыта.
- НЕ повторяй свои предыдущие вопросы.

СТИКЕРЫ И МЕДИА:
- Если получил [стикер], [фото], [видео] и т.п. — это нормально, просто продолжай разговор.
- На стикеры можно отреагировать коротко: "ахах", "норм", или просто продолжить тему.
- НЕ пиши никаких команд в квадратных скобках типа [HANDOFF] или [NEGATIVE_FINISH] — это запрещено.
- Просто пиши обычный текст ответа.
"""
        
        # Get last few messages to show AI what was already asked
        recent_questions = []
        for msg in dialogue.messages[-6:]:
            if msg.role == MessageRole.ACCOUNT and "?" in msg.content:
                recent_questions.append(msg.content)
        
        if recent_questions:
            system_prompt += f"\n\nТы уже спрашивал: {'; '.join(recent_questions[:3])}\nНЕ ПОВТОРЯЙ эти вопросы."
        
        # Add stage hints based on message count
        our_messages = len([m for m in dialogue.messages if m.role == MessageRole.ACCOUNT])
        min_before_goal = campaign.goal.min_messages_before_goal or 5
        
        if not dialogue.goal_message_sent:
            if our_messages >= min_before_goal:
                system_prompt += """

СЕЙЧАС: можно упомянуть что у тебя есть канал где кидаешь сетапы.
Скажи что-то типа: "я у себя в канале такое расписывал" или "у меня есть канал, если интересно".
НЕ навязывай — просто упомяни естественно, если к месту.
"""
            elif our_messages >= min_before_goal - 2:
                system_prompt += """

СКОРО: можно будет упомянуть свой канал. Пока просто веди диалог естественно.
"""
        
        # Get conversation history
        history = dialogue.get_conversation_history(max_messages=8)  # Last 8 like in old project
        
        response = await self.ai_provider.generate(
            messages=history,
            system_prompt=system_prompt,
            model=campaign.ai_model,
            temperature=0.8,  # Same as old project
            max_tokens=campaign.ai_max_tokens,
        )
        
        return response
    
    def _get_default_system_prompt(self) -> str:
        """Get default system prompt based on prompts.py from old project."""
        return """
Ты — обычный частный трейдер по крипте. Не упоминай, что ты бот, ИИ, модель, ассистент.
Представь, что ты живой человек, который давно торгует и иногда делится мыслями в своём телеграм-канале.

ЛЕГЕНДА:
- Раньше сам несколько лет торговал по сигналам из телеграм-каналов.
- Сливал депозиты, ловил маржин-коллы, влетал в хреновые точки входа.
- Потом задолбался, начал сам разбираться: уровни, риск, ликвидность, своя стратегия.
- Со временем вышел из вечного минуса в более-менее стабильный профит.
- Сейчас есть свой небольшой канал/чат, где делишься сетапами и мыслями.
- В канале НЕТ VIP, НЕТ продаваемых сигналов, НЕТ марафонов, НЕТ платных курсов.

АУДИТОРИЯ:
- Почти все торгуют по сигналам с каналов и в основном на фьючерсах.
- Часто сидят в минусе, крутят плечи 10–50х, плохо понимают риск.
- Ты их не осуждаешь — говоришь, что сам был таким же.

ТЕМЫ:
- Биток, эфир, альты, фьючи, плечо, мани-менеджмент, психология трейдинга.
- Можешь рассказывать, как сам когда-то сливался по сигналам.
- Если человек торгует по сигналам или в минусе — отмечай, что сам таким был.

ЦЕНЫ:
- Бычий цикл, биток около 90-100к, эфир 3.5-4к.
- Говори размыто: "в районе", "около", "где-то под".
"""
    
    async def _check_goal_progress(self, dialogue: Dialogue) -> None:
        """Check and update goal progress."""
        if dialogue.goal_message_sent:
            return
        
        campaign = await self.campaign_repo.get_by_id(dialogue.campaign_id)
        if not campaign:
            return
        
        # Check if goal message was delivered
        last_message = dialogue.get_last_message()
        if not last_message or last_message.role != MessageRole.ACCOUNT:
            return
        
        # Simple check: if target URL or key phrase is in message
        goal_delivered = False
        
        if campaign.goal.target_url:
            goal_delivered = campaign.goal.target_url in last_message.content
        elif campaign.goal.target_message:
            # Check for key phrases
            keywords = campaign.goal.target_message.lower().split()[:5]
            message_lower = last_message.content.lower()
            matches = sum(1 for kw in keywords if kw in message_lower)
            goal_delivered = matches >= len(keywords) * 0.6
        
        if goal_delivered:
            dialogue.mark_goal_reached()

            # Update target and campaign
            target = await self.target_repo.get_by_id(dialogue.target_user_id)
            if target:
                target.mark_converted()
                await self.target_repo.save(target)

                # Record conversion (success) to file
                campaign = await self.campaign_repo.get_by_id(dialogue.campaign_id)
                identifier = target.username or str(target.telegram_id)
                await record_target_result(
                    campaign_id=str(dialogue.campaign_id),
                    identifier=identifier,
                    result="success",
                    reason="converted",
                    source_file_path=campaign.sending.targets_file_path if campaign else None,
                )

            await self.campaign_repo.update_stats(
                dialogue.campaign_id,
                goals_reached=1,
            )

            logger.info(
                "Goal reached",
                dialogue_id=str(dialogue.id),
            )
    
    async def get_dialogue(self, dialogue_id: UUID) -> Dialogue:
        """Get dialogue by ID."""
        dialogue = await self.dialogue_repo.get_by_id(dialogue_id)
        if not dialogue:
            raise DialogueNotFoundError(str(dialogue_id))
        return dialogue
    
    async def mark_dialogue_completed(self, dialogue_id: UUID) -> Dialogue:
        """Mark dialogue as completed."""
        dialogue = await self.get_dialogue(dialogue_id)
        dialogue.mark_completed()
        saved = await self.dialogue_repo.save(dialogue)

        # Update target
        target = await self.target_repo.get_by_id(dialogue.target_user_id)
        if target:
            target.mark_completed()
            await self.target_repo.save(target)

            # Record success to file
            campaign = await self.campaign_repo.get_by_id(dialogue.campaign_id)
            identifier = target.username or str(target.telegram_id)
            await record_target_result(
                campaign_id=str(dialogue.campaign_id),
                identifier=identifier,
                result="success",
                source_file_path=campaign.sending.targets_file_path if campaign else None,
            )

        # Update campaign
        await self.campaign_repo.update_stats(
            dialogue.campaign_id,
            completed=1,
        )

        return saved
    
    async def mark_dialogue_failed(
        self,
        dialogue_id: UUID,
        reason: str = "",
    ) -> Dialogue:
        """Mark dialogue as failed."""
        dialogue = await self.get_dialogue(dialogue_id)
        dialogue.mark_failed(reason)
        saved = await self.dialogue_repo.save(dialogue)

        # Update target
        target = await self.target_repo.get_by_id(dialogue.target_user_id)
        if target:
            target.mark_failed(reason)
            await self.target_repo.save(target)

            # Record failure to file
            campaign = await self.campaign_repo.get_by_id(dialogue.campaign_id)
            identifier = target.username or str(target.telegram_id)
            await record_target_result(
                campaign_id=str(dialogue.campaign_id),
                identifier=identifier,
                result="failure",
                reason=reason,
                source_file_path=campaign.sending.targets_file_path if campaign else None,
            )

        # Update campaign
        await self.campaign_repo.update_stats(
            dialogue.campaign_id,
            failed=1,
        )

        return saved
    
    async def list_pending_dialogues(
        self,
        account_id: Optional[UUID] = None,
        limit: int = 100,
    ) -> list[Dialogue]:
        """List dialogues that need follow-up action."""
        return await self.dialogue_repo.list_pending_actions(account_id, limit)
    
    async def list_account_dialogues(
        self,
        account_id: UUID,
        status: Optional[DialogueStatus] = None,
    ) -> list[Dialogue]:
        """List dialogues for an account."""
        return await self.dialogue_repo.list_by_account(account_id, status)
    
    async def generate_follow_up(self, dialogue_id: UUID) -> Optional[str]:
        """
        Generate a follow-up message for a dialogue.

        Used when user hasn't responded in a while.

        Args:
            dialogue_id: Dialogue UUID

        Returns:
            Follow-up message text or None if not needed
        """
        dialogue = await self.dialogue_repo.get_by_id(dialogue_id)
        if not dialogue:
            return None

        # Don't follow up on completed/failed dialogues
        if dialogue.status in (
            DialogueStatus.COMPLETED,
            DialogueStatus.FAILED,
            DialogueStatus.EXPIRED,
        ):
            return None

        # Get campaign
        campaign = await self.campaign_repo.get_by_id(dialogue.campaign_id)
        if not campaign:
            return None

        # Check if follow-up is enabled for this campaign (separate from campaign status)
        if not campaign.sending.follow_up_enabled:
            logger.debug(
                "Follow-up disabled for campaign",
                campaign_id=str(campaign.id),
                dialogue_id=str(dialogue_id),
            )
            return None
        
        # Check how many follow-ups we've sent (max 3)
        follow_up_count = dialogue.get_follow_up_count()
        if follow_up_count >= 3:
            # Too many follow-ups, mark as expired
            dialogue.status = DialogueStatus.EXPIRED
            await self.dialogue_repo.save(dialogue)
            
            # Update target
            target = await self.target_repo.get_by_id(dialogue.target_user_id)
            if target:
                target.mark_failed("No response after 3 follow-ups")
                await self.target_repo.save(target)
            
            return None
        
        # Build system prompt for follow-up
        system_prompt = campaign.get_system_prompt()
        system_prompt += (
            f"\n\nСейчас нужно написать напоминание (follow-up #{follow_up_count + 1}). "
            f"Собеседник не отвечал какое-то время. Напиши естественное "
            f"короткое сообщение, чтобы продолжить разговор. "
            f"Не будь навязчивым. Можно задать вопрос или поделиться чем-то интересным."
        )
        
        # Get conversation history
        history = dialogue.get_conversation_history(max_messages=10)
        
        # Add instruction for follow-up
        history.append({
            "role": "user",
            "content": "[SYSTEM: Пользователь не отвечал. Напиши короткое follow-up сообщение.]"
        })
        
        response = await self.ai_provider.generate(
            messages=history,
            system_prompt=system_prompt,
            model=campaign.ai_model,
            temperature=min(campaign.ai_temperature + 0.1, 1.0),  # Slightly more creative
            max_tokens=150,  # Keep follow-ups short
        )
        
        # Add follow-up message to dialogue
        dialogue.add_message(
            message_id=uuid4(),
            role=MessageRole.ACCOUNT,
            content=response.content,
            ai_generated=True,
            tokens_used=response.total_tokens,
            is_follow_up=True,
        )
        
        # Update next action time (exponential backoff)
        hours_until_next = 24 * (2 ** follow_up_count)  # 24h, 48h, 96h
        dialogue.next_action_at = datetime.utcnow() + timedelta(hours=hours_until_next)
        
        await self.dialogue_repo.save(dialogue)
        
        # Update campaign stats
        await self.campaign_repo.update_stats(
            dialogue.campaign_id,
            messages_sent=1,
            tokens_used=response.total_tokens,
        )
        
        logger.info(
            "Follow-up generated",
            dialogue_id=str(dialogue_id),
            follow_up_number=follow_up_count + 1,
        )
        
        return response.content
