import os
import re
import json
import logging
import dateparser
from datetime import datetime, timezone
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
USER_TIMEZONE = os.environ.get("USER_TIMEZONE", "UTC")  # e.g. "Africa/Lagos"

client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """You are a sharp, warm personal assistant for {name}. Your job is to help them stay organised, focused, and on top of their day.

You help with:
- Planning and structuring their day into a clear schedule
- Keeping track of tasks and to-dos mentioned in conversation
- Breaking big goals into small, actionable steps
- Prioritising what actually matters
- Gently bringing them back on track when they seem scattered or distracted
- Setting reminders when asked

Your style:
- Be concise and direct — cut the fluff
- Warm but not overly enthusiastic
- Use bullet points and structure when listing tasks or plans
- Be proactive: if they mention a task or commitment, acknowledge it and work it into their plan

IMPORTANT — REMINDERS:
If the user asks to be reminded about something, you MUST include this exact block at the very end of your response (after your normal reply), with no extra text after it:
[REMINDER]{{"text": "what to remind them", "time": "when in natural language"}}[/REMINDER]

Example: if the user says "remind me to drink water in 10 minutes", your response ends with:
[REMINDER]{{"text": "Drink water", "time": "in 10 minutes"}}[/REMINDER]

Current time: {current_time}"""

conversation_histories: dict[int, list] = {}


def get_history(user_id: int) -> list:
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []
    return conversation_histories[user_id]


def extract_reminder(text: str):
    """Extract reminder JSON block from AI response. Returns (clean_text, reminder_dict or None)."""
    match = re.search(r'\[REMINDER\](.*?)\[/REMINDER\]', text, re.DOTALL)
    if not match:
        return text, None
    try:
        reminder = json.loads(match.group(1).strip())
        clean_text = text[:match.start()].strip()
        return clean_text, reminder
    except json.JSONDecodeError:
        return text, None


async def reminder_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    await context.bot.send_message(
        chat_id=job.chat_id,
        text=f"⏰ *Reminder:* {job.data}",
        parse_mode="Markdown"
    )


async def ask_ai(
    user_id: int,
    user_name: str,
    message_text: str,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int
) -> str:
    history = get_history(user_id)
    history.append({"role": "user", "content": message_text})

    if len(history) > 30:
        history = history[-30:]
        conversation_histories[user_id] = history

    current_time = datetime.now(timezone.utc).strftime("%A, %B %d %Y at %H:%M UTC")

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(name=user_name, current_time=current_time)}
        ] + history,
        max_tokens=1024,
    )

    raw_message = response.choices[0].message.content
    clean_message, reminder = extract_reminder(raw_message)

    if reminder:
        remind_at_str = reminder.get("time", "")
        reminder_text = reminder.get("text", "")

        remind_time = dateparser.parse(
            remind_at_str,
            settings={
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "future",
                "TIMEZONE": USER_TIMEZONE
            }
        )

        if remind_time:
            context.job_queue.run_once(
                callback=reminder_callback,
                when=remind_time,
                chat_id=chat_id,
                data=reminder_text,
                name=f"reminder_{user_id}_{int(remind_time.timestamp())}"
            )
            formatted_time = remind_time.strftime("%I:%M %p on %A, %B %d").lstrip("0")
            clean_message += f"\n\n✅ Reminder set for *{formatted_time}*."
        else:
            clean_message += "\n\n⚠️ I couldn't understand that time. Try something like 'tomorrow at 7am' or 'in 30 minutes'."

    history.append({"role": "assistant", "content": clean_message})
    return clean_message


async def send_reply(update: Update, text: str) -> None:
    if len(text) <= 4096:
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        for i in range(0, len(text), 4096):
            await update.message.reply_text(text[i:i + 4096], parse_mode="Markdown")


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
        f"• Set reminders ⏰\n\n"
        f"Send me a text or voice note — what's on your plate today?"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conversation_histories[update.effective_user.id] = []
    await update.message.reply_text("Fresh start! 🧹 Conversation cleared.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Here's what I can do:\n\n"
        "/start — Reset and start fresh\n"
        "/clear — Clear conversation history\n"
        "/reminders — See your upcoming reminders\n"
        "/help — Show this message\n\n"
        "Just talk to me naturally:\n"
        "_'Remind me to call mum at 6pm'_\n"
        "_'Wake me up at 7am tomorrow'_\n"
        "_'Help me plan my day'_",
        parse_mode="Markdown"
    )


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    jobs = context.job_queue.jobs()
    user_jobs = [j for j in jobs if j.name and j.name.startswith(f"reminder_{user_id}_")]

    if not user_jobs:
        await update.message.reply_text("You have no upcoming reminders.")
        return

    lines = ["⏰ *Your upcoming reminders:*\n"]
    for job in sorted(user_jobs, key=lambda j: j.next_t):
        time_str = job.next_t.strftime("%I:%M %p, %A %B %d").lstrip("0")
        lines.append(f"• {job.data} — _{time_str}_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        reply = await ask_ai(
            user.id, user.first_name or "there",
            update.message.text, context, update.effective_chat.id
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"⚠️ Error: {e}")
        return

    await send_reply(update, reply)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        voice_bytes = await voice_file.download_as_bytearray()

        transcription = client.audio.transcriptions.create(
            file=("voice.ogg", bytes(voice_bytes), "audio/ogg"),
            model="whisper-large-v3-turbo",
        )
        text = transcription.text
        logger.info(f"Transcribed: {text}")

        await update.message.reply_text(f"🎙️ _{text}_", parse_mode="Markdown")

        reply = await ask_ai(
            user.id, user.first_name or "there",
            text, context, update.effective_chat.id
        )
    except Exception as e:
        logger.error(f"Voice error: {e}")
        await update.message.reply_text(f"⚠️ Error: {e}")
        return

    await send_reply(update, reply)


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN is not set")
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reminders", list_reminders))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
