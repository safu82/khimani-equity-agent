"""
memory.py
Manages conversation history in Supabase so the agent remembers
context across sessions.
"""
import os
import json
from datetime import datetime
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

CHAT_ID      = os.getenv("TELEGRAM_CHAT_ID")
MAX_MESSAGES = 40   # keep last 40 messages in full
SUMMARY_AFTER = 30  # summarise when history exceeds this


def load_history() -> list[dict]:
    """Load conversation history for this user from Supabase."""
    try:
        result = sb.table("conversations") \
                   .select("messages, summary") \
                   .eq("user_id", CHAT_ID) \
                   .limit(1) \
                   .execute()

        if result.data:
            row = result.data[0]
            messages = row.get("messages") or []
            summary  = row.get("summary")

            # If there's a summary, prepend it as a system context message
            if summary and len(messages) > 0:
                return [{"role": "user",      "content": f"[Previous context: {summary}]"},
                        {"role": "assistant",  "content": "Understood, I have the context from our previous conversations."}] + messages
            return messages
        return []
    except Exception as e:
        print(f"Warning: Could not load history: {e}")
        return []


def save_history(messages: list[dict]) -> None:
    """Save updated conversation history to Supabase."""
    try:
        # Only keep the last MAX_MESSAGES messages
        trimmed = messages[-MAX_MESSAGES:]

        existing = sb.table("conversations") \
                     .select("id") \
                     .eq("user_id", CHAT_ID) \
                     .limit(1) \
                     .execute()

        data = {
            "user_id":    CHAT_ID,
            "messages":   trimmed,
            "updated_at": datetime.utcnow().isoformat(),
        }

        if existing.data:
            sb.table("conversations") \
              .update(data) \
              .eq("user_id", CHAT_ID) \
              .execute()
        else:
            sb.table("conversations").insert(data).execute()

    except Exception as e:
        print(f"Warning: Could not save history: {e}")


def add_message(role: str, content: str) -> list[dict]:
    """Add a single message to history and save."""
    history = load_history()

    # Strip the prepended summary messages before saving
    real_history = [m for m in history
                    if not (m.get("content", "").startswith("[Previous context:"))]

    real_history.append({"role": role, "content": content})
    save_history(real_history)
    return real_history


def save_summary(summary: str) -> None:
    """Save a compressed summary of older conversation context."""
    try:
        existing = sb.table("conversations") \
                     .select("id") \
                     .eq("user_id", CHAT_ID) \
                     .limit(1) \
                     .execute()

        if existing.data:
            sb.table("conversations") \
              .update({"summary": summary, "updated_at": datetime.utcnow().isoformat()}) \
              .eq("user_id", CHAT_ID) \
              .execute()
    except Exception as e:
        print(f"Warning: Could not save summary: {e}")


def clear_history() -> None:
    """Clear conversation history (start fresh)."""
    try:
        sb.table("conversations") \
          .update({"messages": [], "summary": None}) \
          .eq("user_id", CHAT_ID) \
          .execute()
        print("✓ Conversation history cleared")
    except Exception as e:
        print(f"Warning: Could not clear history: {e}")


def log_agent_run(run_type: str, month: str, status: str,
                  results: dict = None, errors: dict = None) -> None:
    """Log an agent run to Supabase for debugging."""
    try:
        sb.table("agent_runs").insert({
            "run_type":   run_type,
            "month":      month,
            "status":     status,
            "results":    results or {},
            "errors":     errors or {},
            "created_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception as e:
        print(f"Warning: Could not log agent run: {e}")


if __name__ == "__main__":
    # Test — save and reload a message
    print("Testing memory...")
    add_message("user", "Hello, this is a test message")
    history = load_history()
    print(f"✓ History has {len(history)} message(s)")
    print(f"  Last message: {history[-1]['content']}")
    clear_history()
    print("✓ History cleared")
    print("✓ memory.py working correctly")
