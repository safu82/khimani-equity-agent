"""
agent.py
The Claude-powered reasoning engine for the Khimani Equity Agent.
Receives messages, decides which tools to call, and formulates responses.
"""
import os
import json
from datetime import datetime
import anthropic
from dotenv import load_dotenv

from memory import load_history, save_history
from tools import TOOL_DEFINITIONS, execute_tool

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are a portfolio assistant for Sarfaraz Khimani, a Mumbai-based
proprietary trader. You manage his Indian equity portfolio held via HDFC Securities.

Data sources:
- Supabase: holdings, live_prices, transactions, portfolio_snapshots, cash_flows, alerts, entry_signals
- All prices are sourced from the Zerodha KiteConnect API and stored in live_prices

Key facts:
- Portfolio enum value: 'INDIAN'
- Benchmark: NIFTYBEES purchased at ₹198.04 on Jan 2, 2023
- Use Indian number formatting: ₹13.54L not ₹1,354,000; ₹2.3Cr not ₹23,000,000
- 1L = 100,000; 1Cr = 10,000,000

Your personality:
- Concise and direct — no unnecessary padding
- Lead with the most interesting insight, not just raw numbers
- When showing P&L, always show both absolute (₹) and percentage
- If something looks unusual (large drawdown, big mover) point it out
- IMPORTANT: Answer ONLY the current question. Never repeat or summarise previous answers.
  Use conversation history only for context (e.g. which stock was last discussed).

Formatting for Telegram (use consistently):
- *bold* for key numbers and headers
- Use ₹ with L for lakhs, Cr for crores, K for thousands
- Use 📈 📉 📊 💰 ⚠️ sparingly for visual hierarchy
- Keep responses under 300 words unless the user asks for detail
- For tables, use monospace with backticks

Today's date: {today}
"""


def run_agent(user_message: str) -> str:
    """
    Process a user message through Claude with tool use.
    Returns the final text response.
    """
    # Load conversation history
    history = load_history()

    # Add user message
    history.append({"role": "user", "content": user_message})

    system = SYSTEM_PROMPT.format(
        today=datetime.now().strftime("%d %B %Y"),
    )

    # Agentic loop — Claude keeps calling tools until it's done
    messages       = history.copy()
    final_response = ""
    max_iterations = 10
    iteration      = 0

    while iteration < max_iterations:
        iteration += 1

        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=4096,
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            messages.append({
                "role":    "assistant",
                "content": response.content,
            })

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    print(f"  -> Calling tool: {block.name}({json.dumps(block.input)[:100]})")
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result,
                    })

            messages.append({
                "role":    "user",
                "content": tool_results,
            })

        elif response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    final_response = block.text
                    break
            break

        else:
            final_response = "I encountered an unexpected issue. Please try again."
            break

    if not final_response:
        final_response = "I wasn't able to complete that request. Please try again."

    # Save only clean user/assistant turns to history
    clean_history = [m for m in messages
                     if isinstance(m.get("content"), str)
                     and m["role"] in ("user", "assistant")]

    clean_history = clean_history[-10:]
    save_history(clean_history)

    return final_response


if __name__ == "__main__":
    print("Testing equity agent...\n")
    response = run_agent("What is my portfolio worth today?")
    print("Agent response:")
    print("-" * 50)
    print(response)
    print("-" * 50)
    print("\n✓ agent.py working correctly")
