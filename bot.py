import os
import logging
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """You are a sharp, warm personal assistant. Your job is to help the user stay organised, focused, and on top of their day.

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
        f"Hey {name}! 👋 I'm your personal assistant, powered by Gemini.\n\n"
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
    message_text = update.message.text

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    history = get_history(user_id)

    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=SYSTEM_PROMPT
        )
        chat = model.start_chat(history=history)
        response = chat.send_message(message_text)
        assistant_message = response.text

        history.append({"role": "user", "parts": [message_text]})
        history.append({"role": "model", "parts": [assistant_message]})

        if len(history) > 60:
            conversation_histories[user_id] = history[-60:]

    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        await update.message.reply_text(f"⚠️ Error: {e}")
        return

    if len(assistant_message) <= 4096:
        await update.message.reply_text(assistant_message)
    else:
        for i in range(0, len(assistant_message), 4096):
            await update.message.reply_text(assistant_message[i:i + 4096])


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY environment variable is not set")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
