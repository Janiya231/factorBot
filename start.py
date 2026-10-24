

import os
import subprocess
import sys

import bot

bot.register_webhook()

port = os.environ.get("PORT", "10000")

os.execvp(
    "gunicorn",
    [
        "gunicorn",
        "--workers", "1",
        "--threads", "4",
        "--timeout", "120",
        "--bind", f"0.0.0.0:{port}",
        "bot:app",
    ],
)
