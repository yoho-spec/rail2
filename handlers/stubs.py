"""
handlers/stubs.py
Placeholder responses for commands that will be built in Parts 2–8.
Each stub tells the user what's coming and which part builds it.
"""
from telegram import Update
from telegram.ext import ContextTypes

STUBS = {
    "login":      ("🔑 Account Login", "Part 2 — User Account Login (coming next)"),
    "logout":     ("🚪 Logout", "Part 2 — User Account Login"),
    "mychats":    ("💬 My Chats", "Part 2 — requires account login"),
    "archive":    ("📦 Archive Setup", "Part 3 — Archiver Core"),
    "setdest":    ("📍 Set Destination", "Part 3 — Archiver Core"),
    "duplicates": ("🔍 Duplicate Checker", "Part 4 — Duplicate Detector"),
    "premium":    ("⭐ Premium Status", "Part 8 — Premium System"),
    "search":     ("🔎 History Search", "Part 7 — AI & Search (requires login)"),
    "translate":  ("🌍 AI Translation", "Part 7 — AI & Search"),
    "transcribe": ("🎙 Audio Transcription", "Part 7 — AI & Search"),
}


async def stub_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text.lstrip("/").split()[0].lower()
    title, note = STUBS.get(command, ("🚧 Coming Soon", "This feature is under development"))

    await update.message.reply_text(
        f"{title}\n\n"
        f"🚧 _{note}_\n\n"
        "The foundation is set up. This command will be fully functional soon.",
        parse_mode="Markdown",
    )
