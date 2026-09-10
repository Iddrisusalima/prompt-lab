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
    the same thing. Prove it to yourself: tell the bot your name, run /reset,
    then ask for your name again and watch "tokens in" collapse.

Commands (while chatting)
    /reset      clear the conversation history and start fresh
    /stats      show the running session totals
    /persona    list personas, or switch with: /persona pirate
    /stream     toggle word-by-word streaming on or off
    /help       list commands
    exit        quit

Command line flags
    --model NAME      pick a model, e.g. --model gemini-3.6-flash
    --persona NAME    start with a persona, e.g. --persona teacher
    --no-stream       wait for the full reply instead of streaming it
    --list-models     show available models and exit

Run it with:
    .\venv\Scripts\python.exe chat.py
    .\venv\Scripts\python.exe chat.py --persona pirate --model gemini-3.6-flash
"""

import argparse
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
# Persona library (stretch goal)
#
# Same model, same question, completely different behaviour. Try asking
# "what is 15 + 27?" under each of these -- the teacher will refuse to tell you.
# Remember the persona is sent as input tokens on EVERY request, so a long
# persona is a tax you pay every turn.
# ---------------------------------------------------------------------------
PERSONAS = {
    "tutor": (
        "You are a friendly, concise coding tutor. Keep answers to 2-3 "
        "sentences unless asked for more detail."
    ),
    "pirate": (
        "You are a grumpy 18th-century pirate. Speak in heavy pirate slang, "
        "complain constantly, and reluctantly answer the question anyway."
    ),
    "teacher": (
        "You are a strict primary school maths teacher. Never give the answer "
        "outright. Instead ask exactly one guiding question that helps the "
        "student work it out themselves."
    ),
    "terse": (
        "Answer in the fewest words possible. No greetings, no pleasantries, "
        "no follow-up questions. Often one word is enough."
    ),
    "rubberduck": (
        "You are a rubber duck debugging companion. Never solve the problem. "
        "Ask short clarifying questions that make the developer explain their "
        "own reasoning until they spot the bug themselves."
    ),
}

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


# ---------------------------------------------------------------------------
# Command line arguments (stretch goal)
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chat with a Gemini model and track tokens and cost.",
        epilog="Values not given here fall back to your .env file.",
    )
    parser.add_argument(
        "--model",
        help="model to use, e.g. gemini-3.6-flash (default: GEMINI_MODEL in .env)",
    )
    parser.add_argument(
        "--persona",
        choices=sorted(PERSONAS),
        default="tutor",
        help="which system prompt to start with (default: tutor)",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="wait for the whole reply instead of streaming it word by word",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="list models your key can use, then exit",
    )
    return parser.parse_args()


args = parse_args()

# ---------------------------------------------------------------------------
# Configuration. Command line flags win over .env values.
# ---------------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = args.model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

if not API_KEY or API_KEY == "paste-your-key-here":
    die(
        "No API key found.\n"
        "  Fix: copy .env.example to .env, then paste your real key into "
        "GEMINI_API_KEY.\n"
        "  Get a free key at https://aistudio.google.com/apikey"
    )

client = genai.Client(api_key=API_KEY)

# --list-models is a "do one thing and quit" flag, so handle it before the loop.
if args.list_models:
    print(f"{C.BOLD}Models your key can use for chat:{C.RESET}")
    try:
        for m in client.models.list():
            if "generateContent" in (m.supported_actions or []):
                name = (m.name or "").removeprefix("models/")
                priced = "" if name in PRICING_PER_1M else f"  {C.DIM}(no pricing on file){C.RESET}"
                print(f"  {name}{priced}")
    except Exception as err:
        die(f"Could not list models. {type(err).__name__}: {err}")
    print(
        f"\n{C.DIM}Note: this list is optimistic. Some models it shows will "
        f"still fail when called,\nbecause they are retired for new accounts. "
        f"The only real test is calling one.{C.RESET}"
    )
    sys.exit(0)

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


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

# THE CONVERSATION HISTORY. This list is the entire memory of the bot.
history: list[types.Content] = []

# Running session totals (Day 5).
session = {"turns": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}

persona_name = args.persona
system_prompt = PERSONAS[persona_name]
streaming = not args.no_stream


def add_turn(role: str, text: str) -> None:
    """Append one message to the history.

    role is "user" for my messages, "model" for the bot's replies.
    (OpenAI calls that second role "assistant"; Gemini calls it "model".)
    """
    history.append(types.Content(role=role, parts=[types.Part.from_text(text=text)]))


def config() -> types.GenerateContentConfig:
    return types.GenerateContentConfig(system_instruction=system_prompt)


def send_once() -> tuple[str, types.GenerateContentResponseUsageMetadata]:
    """Send the full history and wait for the complete reply."""
    response = client.models.generate_content(
        model=MODEL,
        contents=history,  # the whole conversation, every single time
        config=config(),
    )
    return (response.text or "").strip(), response.usage_metadata


def send_streaming() -> tuple[str, types.GenerateContentResponseUsageMetadata]:
    """Send the full history and print the reply as it arrives (stretch goal).

    Streaming does not change what you pay -- the token usage still comes back,
    it just arrives on the final chunk. What changes is perceived speed: you see
    the first words almost immediately instead of waiting for the whole reply.
    """
    print(f"\n{C.BOLD}{C.BLUE}Bot:{C.RESET} ", end="", flush=True)

    pieces: list[str] = []
    usage = None

    for chunk in client.models.generate_content_stream(
        model=MODEL, contents=history, config=config()
    ):
        if chunk.text:
            print(chunk.text, end="", flush=True)
            pieces.append(chunk.text)
        # Usage arrives on the final chunk, so keep the last one we are given.
        if chunk.usage_metadata:
            usage = chunk.usage_metadata

    print()  # end the streamed line
    return "".join(pieces).strip(), usage


def explain_api_error(err: errors.APIError) -> str:
    """Turn an SDK exception into something a human can act on.

    The status code tells you which of these it is, and they need different
    responses -- retrying a bad key is pointless, retrying a rate limit is not.
    """
    code = getattr(err, "code", None)

    if code in (400, 401, 403):
        return (
            f"Your API key was rejected (HTTP {code}).\n"
            "  Check GEMINI_API_KEY in your .env file for typos or extra spaces.\n"
            "  Get a fresh key at https://aistudio.google.com/apikey"
        )
    if code == 404:
        return (
            f"The model '{MODEL}' was not found (HTTP 404).\n"
            "  Note your key is fine -- a 404 means auth succeeded and only the\n"
            "  model name is wrong. Try --list-models to see what is available."
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
    input_cost = session["input_tokens"] / 1_000_000 * INPUT_PER_1M
    output_cost = session["output_tokens"] / 1_000_000 * OUTPUT_PER_1M

    print(f"\n{C.CYAN}{'-' * 66}{C.RESET}")
    print(f"{C.BOLD}  SESSION TOTALS{C.RESET}")
    print(f"    model           : {MODEL}")
    print(f"    persona         : {persona_name}")
    print(f"    turns completed : {session['turns']}")
    print(f"    messages in history: {len(history)}")
    print(
        f"    input tokens    : {session['input_tokens']:>7,}"
        f"   ${input_cost:.6f}"
    )
    print(
        f"    output tokens   : {session['output_tokens']:>7,}"
        f"   ${output_cost:.6f}"
    )
    print(f"    total tokens    : {total_tokens:>7,}")
    print(
        f"    estimated cost  : {C.GREEN}${session['cost']:.6f}{C.RESET}"
        f"  {C.DIM}(free tier: actually $0.00){C.RESET}"
    )
    if total_tokens:
        share = session["input_tokens"] / total_tokens * 100
        print(
            f"    {C.DIM}{share:.0f}% of those tokens were input -- that is the "
            f"cost of memory.{C.RESET}"
        )
    print(f"{C.CYAN}{'-' * 66}{C.RESET}")


def show_help() -> None:
    print(f"\n{C.BOLD}Commands{C.RESET}")
    print(f"  {C.CYAN}/reset{C.RESET}     clear the conversation history")
    print(f"  {C.CYAN}/stats{C.RESET}     show running session totals")
    print(f"  {C.CYAN}/persona{C.RESET}   list personas, or switch: /persona pirate")
    print(f"  {C.CYAN}/stream{C.RESET}    toggle word-by-word streaming")
    print(f"  {C.CYAN}/help{C.RESET}      this list")
    print(f"  {C.CYAN}exit{C.RESET}       quit")


def handle_persona(argument: str) -> None:
    """List personas, or switch to one."""
    global persona_name, system_prompt

    if not argument:
        print(f"\n{C.BOLD}Personas{C.RESET}  {C.DIM}(current: {persona_name}){C.RESET}")
        for name, prompt in PERSONAS.items():
            marker = f"{C.GREEN}*{C.RESET}" if name == persona_name else " "
            print(f"  {marker} {C.CYAN}{name:<11}{C.RESET}{prompt[:52]}...")
        print(f"\n  {C.DIM}Switch with: /persona pirate{C.RESET}")
        return

    if argument not in PERSONAS:
        print(
            f"\n{C.YELLOW}No persona called '{argument}'.{C.RESET} "
            f"Options: {', '.join(sorted(PERSONAS))}"
        )
        return

    persona_name = argument
    system_prompt = PERSONAS[argument]
    print(
        f"\n{C.GREEN}Persona switched to '{argument}'.{C.RESET}\n"
        f"  {C.DIM}History is kept, so the bot still remembers the conversation "
        f"-- only its\n  instructions changed. Ask the same question again to "
        f"compare.{C.RESET}"
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
print(f"{C.BLUE}{'=' * 66}{C.RESET}")
print(
    f"{C.BOLD}  Prompt Lab{C.RESET}  {C.DIM}|{C.RESET}  "
    f"model: {C.CYAN}{MODEL}{C.RESET}  {C.DIM}|{C.RESET}  "
    f"persona: {C.CYAN}{persona_name}{C.RESET}"
    f"  {C.DIM}|{C.RESET}  streaming: {C.CYAN}{'on' if streaming else 'off'}{C.RESET}"
)
print(f"  {C.DIM}/reset  /stats  /persona  /stream  /help  exit{C.RESET}")
print(f"{C.BLUE}{'=' * 66}{C.RESET}")

while True:
    try:
        raw = input(f"\n{C.BOLD}{C.GREEN}You:{C.RESET} ")
        # Strip control characters before whitespace. On Windows, pressing
        # Ctrl+V in a console does not paste -- it inserts a literal \x16
        # control character. Without this, such input looks non-empty to
        # Python but arrives at the model as nothing, so we would pay for a
        # request that says nothing. Filter those out and treat as empty.
        user_input = "".join(ch for ch in raw if ch.isprintable() or ch == "\t")
        user_input = user_input.strip()
    except (EOFError, KeyboardInterrupt):
        # EOFError: piped input ran out. KeyboardInterrupt: user pressed Ctrl+C.
        print(f"\n{C.DIM}Interrupted.{C.RESET}")
        break

    # Piped input is not echoed by the terminal, which makes scripted demo
    # transcripts unreadable. Echo it manually in that case.
    if not sys.stdin.isatty():
        print(user_input)

    if not user_input:
        # Say why, instead of silently looping. If the user pressed Ctrl+V
        # expecting a paste, they need to know it did not work.
        if raw.strip():
            print(
                f"  {C.YELLOW}That input was empty once control characters were "
                f"removed.{C.RESET}\n"
                f"  {C.DIM}Ctrl+V does not paste in a Windows console. "
                f"Right-click to paste, or just type.{C.RESET}\n"
                f"  {C.DIM}Nothing was sent, so this cost you nothing.{C.RESET}"
            )
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

    if lowered.split()[0] == "/persona":
        parts = user_input.split(maxsplit=1)
        handle_persona(parts[1].strip().lower() if len(parts) > 1 else "")
        continue

    if lowered == "/stream":
        streaming = not streaming
        state = "on" if streaming else "off"
        print(
            f"\n{C.GREEN}Streaming {state}.{C.RESET}  "
            f"{C.DIM}This changes how the reply appears, not what it costs.{C.RESET}"
        )
        continue

    if lowered == "/reset":
        # Clear memory but KEEP the session totals -- I still spent that money.
        dropped = len(history)
        history.clear()
        print(
            f"\n{C.YELLOW}History cleared.{C.RESET} "
            f"Dropped {dropped} messages. The bot no longer knows anything "
            f"we discussed.\n{C.DIM}Session cost totals are kept -- those "
            f"tokens were already spent. Watch 'tokens in' drop on your next "
            f"message.{C.RESET}"
        )
        continue

    # 1. Add my message to the history.
    add_turn("user", user_input)

    # 2. Send the entire history, handling the ways this can fail.
    try:
        reply, usage = send_streaming() if streaming else send_once()
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

    prompt_tokens = (usage.prompt_token_count or 0) if usage else 0
    output_tokens = (usage.candidates_token_count or 0) if usage else 0
    total_tokens = (usage.total_token_count or 0) if usage else 0

    turn_cost = cost_of(prompt_tokens, output_tokens)

    # Update the running totals.
    session["turns"] += 1
    session["input_tokens"] += prompt_tokens
    session["output_tokens"] += output_tokens
    session["cost"] += turn_cost

    # When streaming, the reply was already printed as it arrived.
    if not streaming:
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
