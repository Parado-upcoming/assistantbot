import os
import logging
from groq import Groq
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

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


async def ask_ai(user_id: int, user_name: str, message_text: str) -> str:
    history = get_history(user_id)
    history.append({"role": "user", "content": message_text})

    if len(history) > 30:
        history = history[-30:]
        conversation_histories[user_id] = history

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_PROMPT.format(name=user_name)}] + history,
        max_tokens=1024,
    )
    assistant_message = response.choices[0].message.content
    history.append({"role": "assistant", "content": assistant_message})
    return assistant_message


async def send_reply(update: Update, text: str) -> None:
    if len(text) <= 4096:
        await update.message.reply_text(text)
    else:
        for i in range(0, len(text), 4096):
            await update.message.reply_text(text[i:i + 4096])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = user.first_name or "there"
    conversation_histories[user.id] = []
    await update.message.reply_text(
        f"Hey {name}! 👋 I'm your personal assistant.\n\n"
        f"I can help you:\n"
        f"• Plan your day 📅\n"
        f"• Track and organise your tasks ✅\n"
        f"• Stay focused and beat distractions 🎯\n"
        f"• Break down big goals into steps 🪜\n\n"
        f"Send me a text or a voice note — what's on your plate today?"
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
        "Send me a text or voice note and I'll help you plan and stay on track."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        reply = await ask_ai(user.id, user.first_name or "there", update.message.text)
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        await update.message.reply_text(f"⚠️ Error: {e}")
        return

    await send_reply(update, reply)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        # Download voice note from Telegram
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        voice_bytes = await voice_file.download_as_bytearray()

        # Transcribe with Groq Whisper
        transcription = client.audio.transcriptions.create(
            file=("voice.ogg", bytes(voice_bytes), "audio/ogg"),
            model="whisper-large-v3-turbo",
        )
        text = transcription.text
        logger.info(f"Transcribed: {text}")

        # Show the user what was heard
        await update.message.reply_text(f"🎙️ _{text}_", parse_mode="Markdown")

        # Pass transcription to AI
        reply = await ask_ai(user.id, user.first_name or "there", text)

    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text(f"⚠️ Error: {e}")
        return

    await send_reply(update, reply)


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN environment variable is not set")
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY environment variable is not set")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
