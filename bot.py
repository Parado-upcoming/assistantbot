import os
import logging
from anthropic import Anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

client = Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are a sharp, warm personal assistant for {name}. Your job is to help them stay organised, focused, and on top of their day.

You help with:
- Planning and structuring their day into a clear schedule
- Keeping track of tasks and to-dos mentioned in conversation
- Breaking big goals into small, actionable steps
- Prioritising what actually matters
- Gently bringing them back on track when they seem scattered or distracted

Your style:
- Be concise and direct — cut the fluff
- Warm but not overly enthusiastic
- Use bullet points and structure when listing tasks or plans
- Be proactive: if they mention a task or commitment, acknowledge it and work it into their plan
- If they ask to plan their day, first ask what fixed commitments they have, then build a realistic schedule around those

You have memory within this conversation — refer back to tasks or plans mentioned earlier when relevant."""

# Per-user conversation history (in-memory)
conversation_histories: dict[int, list] = {}


def get_history(user_id: int) -> list:
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []
    return conversation_histories[user_id]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = user.first_name or "there"

    conversation_histories[user.id] = []

    await update.message.reply_text(
        f"Hey {name}! 👋 I'm your personal assistant, powered by Claude.\n\n"
        f"I can help you:\n"
        f"• Plan your day 📅\n"
        f"• Track and organise your tasks ✅\n"
        f"• Stay focused and beat distractions 🎯\n"
        f"• Break down big goals into steps 🪜\n\n"
        f"Just talk to me like you would a real assistant — what's on your plate today?"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conversation_histories[update.effective_user.id] = []
    await update.message.reply_text("Fresh start! 🧹 Conversation cleared. What are we working on?")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Here's what I can do:\n\n"
        "/start — Reset and start fresh\n"
        "/clear — Clear our conversation history\n"
        "/help — Show this message\n\n"
        "Or just message me normally — tell me what you need to get done today, and I'll help you plan it."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    user_name = user.first_name or "there"
    message_text = update.message.text

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    history = get_history(user_id)
    history.append({"role": "user", "content": message_text})

    # Keep last 30 messages to stay within token limits
    if len(history) > 30:
        history = history[-30:]
        conversation_histories[user_id] = history

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT.format(name=user_name),
            messages=history,
        )
        assistant_message = response.content[0].text
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        await update.message.reply_text(
            "Sorry, I ran into an issue reaching Claude. Try again in a moment."
        )
        return

    history.append({"role": "assistant", "content": assistant_message})

    # Telegram max message length is 4096 chars — split if needed
    if len(assistant_message) <= 4096:
        await update.message.reply_text(assistant_message)
    else:
        for i in range(0, len(assistant_message), 4096):
            await update.message.reply_text(assistant_message[i:i + 4096])


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set")
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
