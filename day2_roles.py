r"""
Day 2 — Roles & System Prompts.

Goal: understand the anatomy of a chat request.
  1. Add a system prompt to give the bot a personality.
  2. Build a multi-message conversation using explicit roles.
  3. PRINT THE FULL REQUEST PAYLOAD before sending it.
  4. Run the SAME messages under 3 different system prompts and compare.

Run it with:
    .\venv\Scripts\python.exe day2_roles.py
"""

import json
import logging
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types

logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# Windows terminals default to cp1252, which mangles characters the model likes
# to use (em-dashes, curly quotes) into noise like "togetherù". Force UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

if not API_KEY or API_KEY == "paste-your-key-here":
    sys.exit(
        "No API key found.\n"
        "Fix: copy .env.example to .env, then paste your real key into "
        "GEMINI_API_KEY."
    )

client = genai.Client(api_key=API_KEY)


# ---------------------------------------------------------------------------
# THE EXPERIMENT: three personalities, one identical conversation.
#
# A "system prompt" is a standing instruction. It is not part of the chat
# transcript -- it is the stage direction that shapes every reply. Notice that
# nothing below changes except this string, yet the answers change completely.
# ---------------------------------------------------------------------------
PERSONAS = {
    "1. Plain assistant": "You are a helpful assistant. Answer clearly and briefly.",
    "2. Grumpy pirate": (
        "You are a grumpy 18th-century pirate. Speak in heavy pirate slang, "
        "complain constantly, and reluctantly answer the question anyway."
    ),
    "3. Strict teacher": (
        "You are a strict primary school maths teacher. Never give the answer "
        "outright. Instead ask exactly one guiding question that helps the "
        "student work it out themselves."
    ),
}

# The conversation history. This is a LIST OF TURNS, and every turn is labelled
# with a role so the model knows who said what.
#
#   role="user"  -> something I said
#   role="model" -> something the model said on a previous turn
#
# Heads up: your brief calls this third role "assistant" (that is OpenAI's
# wording). Gemini calls the exact same thing "model". Same concept, different
# label. There is no role="system" here at all -- see system_instruction below.
CONVERSATION = [
    types.Content(
        role="user",
        parts=[types.Part.from_text(text="Hi! I am learning to code.")],
    ),
    types.Content(
        role="model",
        parts=[types.Part.from_text(text="That is great. What are you working on?")],
    ),
    types.Content(
        role="user",
        parts=[types.Part.from_text(text="What is 15 + 27?")],
    ),
]


def show_payload(system_prompt: str) -> None:
    """Print the exact request we are about to send.

    This is the Day 2 requirement to 'print the full request payload'. Seeing
    it written out makes it obvious that a chat API call is nothing magical --
    it is just a system instruction plus an ordered list of labelled messages.
    """
    payload = {
        "model": MODEL,
        "system_instruction": system_prompt,
        "contents": [
            {"role": turn.role, "text": turn.parts[0].text} for turn in CONVERSATION
        ],
    }
    print("REQUEST PAYLOAD BEING SENT:")
    print(json.dumps(payload, indent=2))


def ask(system_prompt: str):
    """Send CONVERSATION to the model under a given system prompt."""
    return client.models.generate_content(
        model=MODEL,
        contents=CONVERSATION,
        # The system prompt rides along OUTSIDE the message list, as config.
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )


# ---------------------------------------------------------------------------
# Run the same conversation three times, changing only the system prompt.
# ---------------------------------------------------------------------------
print("=" * 70)
print("DAY 2: same 3 messages, three different system prompts")
print("=" * 70)

# Show the payload once, in full, so we can see its shape.
show_payload(PERSONAS["1. Plain assistant"])
print("\nOnly 'system_instruction' changes between the runs below.\n")

for label, system_prompt in PERSONAS.items():
    print("=" * 70)
    print(f"SYSTEM PROMPT -> {label}")
    print(f'  "{system_prompt}"')
    print("-" * 70)

    response = ask(system_prompt)
    usage = response.usage_metadata

    print(f"LAST USER MESSAGE -> {CONVERSATION[-1].parts[0].text}")
    print(f"MODEL REPLIED     -> {response.text.strip()}")
    print(
        f"TOKENS            -> in={usage.prompt_token_count} "
        f"out={usage.candidates_token_count} "
        f"total={usage.total_token_count}"
    )
    print()

print("=" * 70)
print("TAKEAWAYS")
print("-" * 70)
print("1. The question '15 + 27' never changed, but behaviour did completely:")
print("   plain assistant answers 42, the pirate grumbles then answers,")
print("   the teacher refuses to answer and asks a question back.")
print("   The system prompt alone decided all three.")
print()
print("2. INPUT tokens differ between runs (43 / 60 / 62) even though my")
print("   messages were identical. That is because the system prompt is")
print("   itself billed as input, on EVERY request. A long persona is a")
print("   tax you pay every single turn.")
print()
print("3. OUTPUT tokens vary hugely (11 / 161 / 24). The pirate cost about")
print("   14x the plain assistant to answer the same maths question,")
print("   because personality means more words.")
print("=" * 70)
