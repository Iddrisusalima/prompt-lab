r"""
Prompt Lab — a CLI chat tool for Google Gemini with token & cost tracking.

What this does
    Holds a conversation with an AI model, remembers everything said so far,
    and reports tokens used and estimated cost after every single reply, plus
    a running total for the whole session.

The one idea worth taking away
    The model is stateless. It remembers nothing between requests. What looks
    like memory is just this script resending the entire transcript every time.
    That is why the "tokens in" number climbs every turn -- memory and cost are
    the same thing.

Commands
    /reset    clear the conversation history and start fresh
    /stats    show the running session totals
    /help     list commands
    exit      quit

Run it with:
    .\venv\Scripts\python.exe chat.py
"""

import logging
import os
import sys

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

# The SDK warns about automatic function calling, which we do not use.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# Windows consoles default to cp1252, which mangles em-dashes and curly quotes
# into noise. If you still see characters like "ΓÇö" when piping output, also run
#     [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# once in your PowerShell session -- that fixes the reading end.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ---------------------------------------------------------------------------
# Colours. Plain ANSI escape codes, no extra dependency.
# Disabled automatically when output is piped to a file, because escape codes
# in a text file are just garbage.
# ---------------------------------------------------------------------------
class C:
    if sys.stdout.isatty():
        BOLD = "\033[1m"
        DIM = "\033[2m"
        RED = "\033[31m"
        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        BLUE = "\033[34m"
        CYAN = "\033[36m"
        RESET = "\033[0m"
    else:
        BOLD = DIM = RED = GREEN = YELLOW = BLUE = CYAN = RESET = ""


def die(message: str) -> None:
    """Print a clean error and exit. No stack traces for the user."""
    print(f"\n{C.RED}{C.BOLD}Error:{C.RESET} {message}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

if not API_KEY or API_KEY == "paste-your-key-here":
    die(
        "No API key found.\n"
        "  Fix: copy .env.example to .env, then paste your real key into "
        "GEMINI_API_KEY.\n"
        "  Get a free key at https://aistudio.google.com/apikey"
    )

SYSTEM_PROMPT = (
    "You are a friendly, concise coding tutor. Keep answers to 2-3 sentences "
    "unless asked for more detail."
)

# ---------------------------------------------------------------------------
# Pricing (Day 4)
#
# Google publishes prices per 1 MILLION tokens. My brief asks for per-1K, which
# is simply these numbers divided by 1000.
#
# Source: https://ai.google.dev/gemini-api/docs/pricing   (checked 2026-09-09)
#
# Honesty note: I am on the FREE tier, where Google charges $0.00. So the costs
# printed below are what this conversation WOULD cost at paid-tier rates. That
# is still the number worth learning to watch, so the tool labels it clearly
# instead of pretending I am being billed.
# ---------------------------------------------------------------------------
PRICING_PER_1M = {
    # model name: (input $ per 1M tokens, output $ per 1M tokens)
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}

if MODEL not in PRICING_PER_1M:
    print(
        f"{C.YELLOW}Note:{C.RESET} no pricing on file for '{MODEL}'. "
        f"Using Flash-Lite rates, so costs shown may be wrong."
    )
INPUT_PER_1M, OUTPUT_PER_1M = PRICING_PER_1M.get(MODEL, (0.30, 2.50))


def cost_of(input_tokens: int, output_tokens: int) -> float:
    """Convert token counts into an estimated US dollar cost.

    Divide by 1_000_000 because prices are quoted per million tokens. Input and
    output are billed at different rates, and output is far more expensive
    (2.50 vs 0.30 here, so roughly 8x per token).
    """
    return (
        input_tokens / 1_000_000 * INPUT_PER_1M
        + output_tokens / 1_000_000 * OUTPUT_PER_1M
    )


client = genai.Client(api_key=API_KEY)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

# THE CONVERSATION HISTORY. This list is the entire memory of the bot.
history: list[types.Content] = []

# Running session totals (Day 5).
session = {"turns": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}


def add_turn(role: str, text: str) -> None:
    """Append one message to the history.

    role is "user" for my messages, "model" for the bot's replies.
    (OpenAI calls that second role "assistant"; Gemini calls it "model".)
    """
    history.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))


def send() -> types.GenerateContentResponse:
    """Send the FULL history to the model."""
    return client.models.generate_content(
        model=MODEL,
        contents=history,  # the whole conversation, every single time
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )


def explain_api_error(err: errors.APIError) -> str:
    """Turn an SDK exception into something a human can act on.

    The status code tells you which of these it is, and they need different
    responses -- retrying a bad key is pointless, retrying a rate limit is not.
    """
    code = getattr(err, "code", None)

    if code in (400, 401, 403):
        return (
            "Your API key was rejected (HTTP "
            f"{code}).\n"
            "  Check GEMINI_API_KEY in your .env file for typos or extra spaces.\n"
            "  Get a fresh key at https://aistudio.google.com/apikey"
        )
    if code == 404:
        return (
            f"The model '{MODEL}' was not found (HTTP 404).\n"
            "  Note your key is fine -- a 404 means auth succeeded and only the\n"
            "  model name is wrong. Change GEMINI_MODEL in your .env file."
        )
    if code == 429:
        return (
            "Rate limit or quota exceeded (HTTP 429).\n"
            "  The free tier allows a limited number of requests per minute and\n"
            "  per day. Wait a minute and try again."
        )
    if code is not None and code >= 500:
        return (
            f"Google's servers returned an error (HTTP {code}).\n"
            "  This is on their end, not yours. Try again shortly."
        )
    return f"API error: {err}"


def show_stats() -> None:
    """Print the running session totals."""
    total_tokens = session["input_tokens"] + session["output_tokens"]
    print(f"\n{C.CYAN}{'-' * 66}{C.RESET}")
    print(f"{C.BOLD}  SESSION TOTALS{C.RESET}")
    print(f"    turns completed : {session['turns']}")
    print(f"    messages in history: {len(history)}")
    print(f"    input tokens    : {session['input_tokens']:,}")
    print(f"    output tokens   : {session['output_tokens']:,}")
    print(f"    total tokens    : {total_tokens:,}")
    print(
        f"    estimated cost  : {C.GREEN}${session['cost']:.6f}{C.RESET}"
        f"  {C.DIM}(free tier: actually $0.00){C.RESET}"
    )
    print(f"{C.CYAN}{'-' * 66}{C.RESET}")


def show_help() -> None:
    print(f"\n{C.BOLD}Commands{C.RESET}")
    print(f"  {C.CYAN}/reset{C.RESET}  clear the conversation history")
    print(f"  {C.CYAN}/stats{C.RESET}  show running session totals")
    print(f"  {C.CYAN}/help{C.RESET}   this list")
    print(f"  {C.CYAN}exit{C.RESET}    quit")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
print(f"{C.BLUE}{'=' * 66}{C.RESET}")
print(f"{C.BOLD}  Prompt Lab{C.RESET}  {C.DIM}|{C.RESET}  model: {C.CYAN}{MODEL}{C.RESET}")
print(f"  {C.DIM}/reset  /stats  /help  exit{C.RESET}")
print(f"{C.BLUE}{'=' * 66}{C.RESET}")

while True:
    try:
        user_input = input(f"\n{C.BOLD}{C.GREEN}You:{C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        # EOFError: piped input ran out. KeyboardInterrupt: user pressed Ctrl+C.
        print(f"\n{C.DIM}Interrupted.{C.RESET}")
        break

    # Piped input is not echoed by the terminal, which makes scripted demo
    # transcripts unreadable. Echo it manually in that case.
    if not sys.stdin.isatty():
        print(user_input)

    if not user_input:
        continue

    lowered = user_input.lower()

    if lowered in {"exit", "quit"}:
        break

    if lowered == "/help":
        show_help()
        continue

    if lowered == "/stats":
        show_stats()
        continue

    if lowered == "/reset":
        # Clear memory but KEEP the session totals -- I still spent that money.
        dropped = len(history)
        history.clear()
        print(
            f"\n{C.YELLOW}History cleared.{C.RESET} "
            f"Dropped {dropped} messages. The bot no longer knows anything "
            f"we discussed.\n{C.DIM}Session cost totals are kept -- those "
            f"tokens were already spent.{C.RESET}"
        )
        continue

    # 1. Add my message to the history.
    add_turn("user", user_input)

    # 2. Send the entire history, handling the ways this can fail.
    try:
        response = send()
    except errors.APIError as err:
        # Remove the message we just added. Leaving an unanswered user turn in
        # history would corrupt the conversation shape for the next request.
        history.pop()
        print(f"\n{C.RED}{C.BOLD}Request failed.{C.RESET} {explain_api_error(err)}")
        continue
    except (httpx.ConnectError, httpx.TimeoutException) as err:
        history.pop()
        print(
            f"\n{C.RED}{C.BOLD}Network problem.{C.RESET} Could not reach Google.\n"
            f"  Check your internet connection and try again.\n"
            f"  {C.DIM}({type(err).__name__}){C.RESET}"
        )
        continue
    except Exception as err:  # last resort, so the tool never hard-crashes
        history.pop()
        print(
            f"\n{C.RED}{C.BOLD}Unexpected error.{C.RESET} "
            f"{type(err).__name__}: {err}"
        )
        continue

    reply = (response.text or "").strip()
    if not reply:
        history.pop()
        print(
            f"\n{C.YELLOW}The model returned an empty reply.{C.RESET} "
            "This usually means a safety filter blocked it. Try rephrasing."
        )
        continue

    # 3. Add the bot's reply to history too. Forgetting this step is the classic
    #    beginner bug -- the bot then cannot remember its own answers.
    add_turn("model", reply)

    usage = response.usage_metadata
    prompt_tokens = usage.prompt_token_count or 0
    output_tokens = usage.candidates_token_count or 0
    total_tokens = usage.total_token_count or 0

    turn_cost = cost_of(prompt_tokens, output_tokens)

    # Update the running totals.
    session["turns"] += 1
    session["input_tokens"] += prompt_tokens
    session["output_tokens"] += output_tokens
    session["cost"] += turn_cost

    print(f"\n{C.BOLD}{C.BLUE}Bot:{C.RESET} {reply}")
    print(
        f"\n  {C.DIM}[turn {session['turns']}]{C.RESET}  "
        f"history: {len(history)} msgs  {C.DIM}|{C.RESET}  "
        f"tokens  in: {C.YELLOW}{prompt_tokens}{C.RESET}  "
        f"out: {C.YELLOW}{output_tokens}{C.RESET}  "
        f"total: {C.YELLOW}{total_tokens}{C.RESET}"
    )
    print(
        f"  this turn: {C.GREEN}${turn_cost:.6f}{C.RESET}   "
        f"session so far: {C.GREEN}${session['cost']:.6f}{C.RESET}  "
        f"({session['input_tokens'] + session['output_tokens']:,} tokens)"
    )

# Always show the final bill on the way out.
show_stats()
print(f"\n{C.DIM}Goodbye.{C.RESET}")
