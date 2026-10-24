
import ast
import os
import re
import secrets
import threading

import requests
import sympy as sp
from flask import Flask, request, abort

app = Flask(__name__)
x = sp.Symbol("x")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()

if not HOST:
    raise RuntimeError("RENDER_EXTERNAL_HOSTNAME is missing")

API = f"https://api.telegram.org/bot{TOKEN}"
MAX_LENGTH = 150


def safe_expression(text):
    """Parse a restricted arithmetic expression; never eval user input."""
    text = text.strip().lower().replace("−", "-").replace("×", "*")
    text = text.replace("^", "**")

    if not text or len(text) > MAX_LENGTH:
        raise ValueError("Expression is empty or too long.")

    # Permit only digits, x, spaces and basic arithmetic punctuation.
    if not re.fullmatch(r"[0-9x+\-*/().\s*]+", text):
        raise ValueError("Unsupported character.")

    # Convert common A/L notation: 2x, x(x+1), 2(x+1).
    text = re.sub(r"(?<=\d)\s*(?=x\b)", "*", text)
    text = re.sub(r"(?<=x)\s*(?=\()", "*", text)
    text = re.sub(r"(?<=\))\s*(?=[x\d(])", "*", text)
    text = re.sub(r"(?<=x)\s*(?=\d)", "*", text)
    text = re.sub(r"(?<=\d)\s*(?=\()", "*", text)

    tree = ast.parse(text, mode="eval")

    def convert(node):
        if isinstance(node, ast.Expression):
            return convert(node.body)

        if isinstance(node, ast.Constant):
            if type(node.value) in (int, float):
                return sp.Rational(str(node.value))
            raise ValueError("Invalid number.")

        if isinstance(node, ast.Name) and node.id == "x":
            return x

        if isinstance(node, ast.UnaryOp):
            value = convert(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
            raise ValueError("Invalid unary operator.")

        if isinstance(node, ast.BinOp):
            a, b = convert(node.left), convert(node.right)

            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                if b == 0:
                    raise ValueError("Division by zero.")
                return a / b
            if isinstance(node.op, ast.Pow):
                if b.is_Integer is not True or abs(int(b)) > 12:
                    raise ValueError("Use integer powers from -12 to 12.")
                return a ** int(b)

        raise ValueError("Unsupported expression.")

    result = convert(tree)

    if result.free_symbols - {x}:
        raise ValueError("Use x as the variable.")

    if not result.is_polynomial(x):
        raise ValueError("Please enter a polynomial.")

    if sp.count_ops(result) > 100:
        raise ValueError("Expression is too complex.")

    return result


def solve(text):
    expr = safe_expression(text)
    expanded = sp.expand(expr)
    factored = sp.factor(expr)

    lines = [
        "🧮 FACTOR FINDER",
        "",
        f"Input: {text}",
        f"Standard form: {sp.sstr(expanded)}",
        "",
        "📘 Working:",
        "1. Identify the terms and their common factors.",
        f"2. Expanded polynomial: {sp.sstr(expanded)}",
    ]

    if expr == 0:
        lines += [
            "3. Zero is already simplified.",
            "",
            "✅ Answer: 0",
        ]
    elif expr.is_number:
        lines += [
            "3. This is a constant; there is no x factor.",
            "",
            f"✅ Answer: {sp.sstr(factored)}",
        ]
    else:
        lines += [
            "3. Factor the polynomial:",
            f"   {sp.sstr(expanded)}",
            "",
            f"✅ Final answer: {sp.sstr(factored)}",
            "",
            f"🔍 Check by expansion: {sp.sstr(sp.expand(factored))}",
        ]

        if factored != expr and x in sp.Mul.make_args(factored):
            lines.append("The common factor x has been taken out.")

    answer = "\n".join(lines)
    if len(answer) > 3900:
        raise ValueError("Result too long.")
    return answer


def send_message(chat_id, text):
    response = requests.post(
        f"{API}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=15,
    )
    response.raise_for_status()


@app.get("/")
def home():
    return "Factor Finder Bot is running.", 200


@app.post("/webhook/" + WEBHOOK_SECRET)
def webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message")

    if not message or not message.get("text"):
        return "OK", 200

    chat_id = message["chat"]["id"]
    text = message["text"].strip()

    if text.startswith("/start") or text.startswith("/help"):
        reply = (
            "👋 Welcome to Factor Finder Bot!\n\n"
            "Send a polynomial expression to factor.\n\n"
            "Examples:\n"
            "2x^2 + 4x\n"
            "x^2 - 9\n"
            "x^2 + 5x + 6\n"
            "x^3 + 2x^2 + x\n\n"
            "Use ^ for powers. Only x-polynomials are supported."
        )
    else:
        try:
            reply = solve(text)
        except Exception:
            reply = (
                "❌ Could not solve that expression.\n\n"
                "Try: x^2 + 5x + 6\n"
                "Supported: +, -, *, /, ^ and parentheses."
            )

    try:
        send_message(chat_id, reply)
    except requests.RequestException:
        app.logger.exception("Telegram sendMessage failed")

    return "OK", 200


def register_webhook():
    url = f"https://{HOST}/webhook/{WEBHOOK_SECRET}"
    response = requests.post(
        f"{API}/setWebhook",
        json={"url": url, "drop_pending_updates": False},
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(f"Could not register webhook: {result}")


if __name__ == "__main__":
    if len(WEBHOOK_SECRET) < 32:
        raise RuntimeError("WEBHOOK_SECRET must be at least 32 characters.")

    register_webhook()

    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
