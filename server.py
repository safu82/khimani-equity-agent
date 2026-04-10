"""
server.py
FastAPI webhook server for the Khimani Equity Agent on Railway.
Receives Telegram messages via webhook instead of polling.
"""
import os
import requests
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, BackgroundTasks
from dotenv import load_dotenv

load_dotenv()

TOKEN    = os.getenv("TELEGRAM_TOKEN")
CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"


# ── Lifespan ──────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await setup_webhook()
    yield


app = FastAPI(lifespan=lifespan)


# ── Webhook setup ─────────────────────────────────────────────────
async def setup_webhook():
    """Register webhook URL with Telegram on startup."""
    railway_url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if not railway_url:
        print("Warning: RAILWAY_PUBLIC_DOMAIN not set — webhook not registered")
        return

    webhook_url = f"https://{railway_url}/webhook"
    r = requests.post(f"{BASE_URL}/setWebhook", json={"url": webhook_url})
    result = r.json()
    if result.get("ok"):
        print(f"✓ Webhook set: {webhook_url}")
    else:
        print(f"✗ Webhook failed: {result}")


# ── Telegram helpers ──────────────────────────────────────────────
def send_message(text: str, parse_mode: str = "Markdown") -> dict:
    """Send a message to the configured Telegram chat."""
    try:
        r = requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id":    CHAT_ID,
            "text":       text,
            "parse_mode": parse_mode,
        })
        if not r.json().get("ok"):
            # Retry without Markdown if formatting fails
            requests.post(f"{BASE_URL}/sendMessage", json={
                "chat_id": CHAT_ID,
                "text":    text,
            })
        return r.json()
    except Exception as e:
        print(f"Warning: Could not send message: {e}")
        return {}


# ── Message handler ───────────────────────────────────────────────
def handle_message(message: dict) -> None:
    """Route incoming text messages."""
    from agent import run_agent
    from memory import clear_history

    text    = message.get("text", "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))

    # Only respond to the configured chat
    if chat_id != CHAT_ID:
        return
    if not text:
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Message: {text}")
    lower = text.lower()

    if lower.startswith("/start"):
        send_message(
            "👋 *Khimani Equity Agent* ready.\n\n"
            "Ask me anything about your Indian portfolio:\n"
            "• _What is my portfolio worth today?_\n"
            "• _How is Infosys performing?_\n"
            "• _Which sector is dragging performance?_\n"
            "• _What signals fired this week?_\n"
            "• _What is my XIRR since January?_\n\n"
            "Say *clear history* to start a fresh conversation."
        )
        return

    if lower == "clear history":
        clear_history()
        send_message("✅ Conversation history cleared.")
        return

    # Everything else → agent
    send_message("_Thinking..._", parse_mode="Markdown")
    response = run_agent(text)
    send_message(response)


# ── FastAPI routes ────────────────────────────────────────────────
@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive Telegram updates via webhook."""
    update = await request.json()

    if "message" in update:
        background_tasks.add_task(handle_message, update["message"])

    return {"ok": True}


@app.get("/health")
async def health():
    return {
        "status":  "ok",
        "service": "Khimani Equity Agent",
        "time":    datetime.now().isoformat(),
    }


@app.get("/")
async def root():
    return {"service": "Khimani Equity Agent", "status": "running"}
