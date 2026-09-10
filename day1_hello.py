r"""
Day 1 — the smallest possible LLM call.

Goal: send ONE message to the model, print ONE reply.
No memory, no cost tracking, no loop. Those come on Days 3-5.

Run it with:
    .\venv\Scripts\python.exe day1_hello.py
"""

import logging
import os
import sys

from dotenv import load_dotenv
from google import genai

# The SDK logs a warning about "automatic function calling" that does not apply
# to us (we aren't using tools). Quiet it so our own output is easy to read.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# load_dotenv() reads the .env file sitting next to this script and copies
# those values into the process environment. This is why the key never
# appears in our source code -- and why .env is in .gitignore.
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# Fail with a human explanation instead of a confusing stack trace.
if not API_KEY or API_KEY == "paste-your-key-here":
    sys.exit(
        "No API key found.\n"
        "Fix: copy .env.example to .env, then paste your real key into "
        "GEMINI_API_KEY.\n"
        "Get a free key at https://aistudio.google.com/apikey"
    )

# The client is just an authenticated HTTP wrapper around Google's servers.
# Creating it does NOT contact the network yet.
client = genai.Client(api_key=API_KEY)

prompt = "In two sentences, explain what an API is to a complete beginner."

# THIS is the network call -- the moment of "inference".
# Your prompt travels to a machine running the model, the model predicts a
# response token by token, and the finished text comes back.
response = client.models.generate_content(
    model=MODEL,
    contents=prompt,
)

print(f"--- You asked ({MODEL}) ---")
print(prompt)
print("\n--- Model replied ---")
print(response.text)

# A peek ahead at Day 4: the response object carries the token bill with it.
print("\n--- Token usage (Day 4 preview) ---")
print(response.usage_metadata)
