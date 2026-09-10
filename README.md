# Prompt Lab

A command-line chat tool for Google's Gemini models that shows you exactly what
every conversation costs. It holds a normal back-and-forth chat, remembers
everything said so far, and after each reply prints the tokens sent, the tokens
received, the estimated price of that turn, and a running total for the whole
session. The point of the project was not just to get a chatbot working but to
make the invisible parts visible: you can watch the token count climb with every
message and see, in real numbers, why memory is the thing you are paying for.

Built as Project 1 of an AI engineering mentorship.

---

## Setup

**Requirements:** Python 3.10 or newer. Developed on Python 3.12.5, Windows.

**1. Clone and enter the project**

```bash
git clone https://github.com/<your-username>/prompt-lab.git
cd prompt-lab
```

**2. Create a virtual environment and install dependencies**

Windows (PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS / Linux:
```bash
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
```

**3. Add your API key**

Get a free key from [Google AI Studio](https://aistudio.google.com/apikey), then
copy the template and fill it in:

```powershell
Copy-Item .env.example .env
```

Open `.env` and set your key:

```
GEMINI_API_KEY=your_real_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
```

`.env` is listed in `.gitignore`, so your key stays on your machine and can never
be committed.

**4. Run it**

```powershell
.\venv\Scripts\python.exe chat.py
```

On Windows, if the model's em-dashes show up as `ΓÇö`, run this once per terminal
session to fix your console's encoding:

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

---

## Usage

### Commands (while chatting)

| Command | What it does |
| --- | --- |
| `/reset` | Clears the conversation history. Cost totals are kept, since those tokens were already spent. |
| `/stats` | Shows the running session totals. |
| `/persona` | Lists personas, or switch with `/persona pirate`. |
| `/stream` | Toggles word-by-word streaming. |
| `/help` | Lists the commands. |
| `exit` | Quits and prints the final bill. |

### Command line flags

| Flag | What it does |
| --- | --- |
| `--model NAME` | Pick a model, overriding `.env`. e.g. `--model gemini-3.6-flash` |
| `--persona NAME` | Start with a persona. One of `tutor`, `pirate`, `teacher`, `terse`, `rubberduck` |
| `--no-stream` | Wait for the whole reply instead of streaming it |
| `--list-models` | List models your key can use, then exit |

```powershell
.\venv\Scripts\python.exe chat.py --persona pirate --model gemini-3.6-flash
```

Note that `--list-models` is optimistic: some models it lists still fail when
called, because they are retired for new accounts. The only real test is calling
one, and the tool reports that failure clearly if it happens.

### Example session

```
==================================================================
  Prompt Lab  |  model: gemini-3.5-flash-lite
  /reset  /stats  /help  exit
==================================================================

You: My name is Salima.

Bot: Nice to meet you, Salima! How can I help you with your coding journey today?

  [turn 1]  history: 2 msgs  |  tokens  in: 31  out: 19  total: 50
  this turn: $0.000057   session so far: $0.000057  (50 tokens)

You: What is my name?

Bot: Your name is Salima! What would you like to code today?

  [turn 2]  history: 4 msgs  |  tokens  in: 57  out: 14  total: 71
  this turn: $0.000052   session so far: $0.000109  (121 tokens)

You: /reset

History cleared. Dropped 4 messages. The bot no longer knows anything we discussed.
Session cost totals are kept -- those tokens were already spent.

You: What is my name?

Bot: I don't have access to your personal information, so I don't know your name
     yet! What should I call you?

  [turn 3]  history: 2 msgs  |  tokens  in: 30  out: 27  total: 57
  this turn: $0.000077   session so far: $0.000185  (178 tokens)

You: exit

------------------------------------------------------------------
  SESSION TOTALS
    turns completed : 3
    messages in history: 2
    input tokens    : 118
    output tokens   : 60
    total tokens    : 178
    estimated cost  : $0.000185  (free tier: actually $0.00)
------------------------------------------------------------------
```

Two things to notice in that transcript. After `/reset` the bot genuinely no
longer knows the name it had just used — memory is not stored anywhere else. And
input tokens dropped from 57 back to 30 on the next turn, because there was less
history to resend.

---

## Pricing

Rates for `gemini-3.5-flash-lite`, from
[Google's official pricing page](https://ai.google.dev/gemini-api/docs/pricing)
(checked 9 September 2026):

| | Per 1M tokens | Per 1K tokens |
| --- | --- | --- |
| Input | $0.30 | $0.0003 |
| Output | $2.50 | $0.0025 |

The free tier costs $0.00, so the figures this tool prints are what the
conversation **would** cost at paid-tier rates. The output labels this plainly
rather than pretending you are being billed. Rates for several other Gemini
models are in the `PRICING_PER_1M` table in `chat.py`, and the tool warns you if
you select a model it has no pricing for.

---

## What I Learned

### Tokens

A token is a chunk of text the model treats as a single unit. It is not a word
and not a letter but something in between: common short words are usually one
token, longer or unusual words get split into several pieces, and punctuation and
spaces count too. A rough rule for English is about 4 characters per token, so
roughly 750 words comes to about 1,000 tokens.

Tokens matter because they are the model's only unit of measurement. The model
never sees text, it sees a sequence of token IDs. So tokens are simultaneously
what the context window is measured in and what you are billed for, in both
directions.

The two surprises for me were that **input and output are priced differently** —
output costs about eight times more per token here — and that
`total_token_count` is **not always input + output**. When I tested
`gemini-3.6-flash` it reported 4 input and 2 output tokens but a total of 62. The
missing 56 were internal "thinking" tokens: billed, but never shown in the reply.
I picked Flash-Lite partly so my cost arithmetic would stay transparent while
learning.

### Context windows

The context window is the maximum number of tokens the model can consider at
once, covering the system prompt, the entire conversation history, and the reply
being generated. For `gemini-3.5-flash-lite` that limit is around one million
tokens.

The part that clicked for me is that the context window is a hard ceiling on a
number that only ever grows. Because memory works by resending the whole
transcript, history accumulates every turn and never shrinks on its own. Eventually
a long enough conversation stops fitting, and at that point you have to start
dropping or summarising old turns. The window is not the model's memory, it is the
size of the desk you are allowed to spread your papers on.

### Roles

A role is a label attached to each message telling the model who said it. Without
those labels the model would receive one undifferentiated block of text and have
no way to tell my words from its own.

- **user** — what I typed.
- **model** — what the bot said on previous turns. *(OpenAI calls this role
  `assistant`; Gemini calls it `model`. Same concept, different name.)*
- **system instruction** — standing rules that shape every reply. In Gemini this
  is not a message in the list at all, it is a separate config field. There is no
  `role="system"`.

Roles are how a stateless model reconstructs a conversation. I proved to myself
how much power sits in the system instruction by sending the identical question
`What is 15 + 27?` under three different system prompts: a plain assistant
answered `42` in 11 output tokens, a grumpy pirate insulted me for 161 tokens
before conceding 42, and a strict teacher refused to give the answer at all and
asked a guiding question instead. Same model, same question, no code changes —
one sentence of instruction changed what the tool actually *does*.

### The idea that tied it all together

The model is completely stateless. It remembers nothing once a request finishes.
So "memory" does not live in the model, it lives in a list on my machine, and it
works by re-sending the whole transcript every single time. The bot never recalled
my name — it re-read me saying it.

Which means memory and cost are the same thing. In my Day 3 test, input tokens
climbed 41 → 74 → 142 → 220 → 295 across five turns while my typed messages
stayed about the same length. Cost therefore grows closer to the *square* of
conversation length than linearly, because turn 10 pays for turns 1 through 9 all
over again. The system prompt is included in that toll on every turn too, which
makes a long elaborate persona a permanent tax rather than a one-off cost.

---

## Error handling

Every one of these was deliberately triggered and observed, not just coded for:

| Failure | Behaviour |
| --- | --- |
| Missing API key | Plain-English fix instructions, exit code 1, no stack trace |
| Invalid API key | `HTTP 401` with where to get a fresh key. The tool keeps running. |
| Unknown model | `HTTP 404`, and it points out that your key is fine since auth succeeded |
| No network | Caught `httpx.ConnectError` and reports a connection problem |
| Rate limit | `HTTP 429` handled with a "wait and retry" message |
| Empty reply | Explains a safety filter probably blocked it, suggests rephrasing |

A failed request never corrupts the conversation. The user message is rolled back
out of history, so the transcript can't end on an unanswered turn and break the
next request.

---

## Project structure

| File | Purpose |
| --- | --- |
| `chat.py` | **The main tool.** Memory, token counting, cost tracking, commands, error handling. |
| `day1_hello.py` | The smallest possible version: one message in, one reply out. |
| `day2_roles.py` | The roles experiment: same conversation under three system prompts, printing the full request payload. |
| `NOTES.md` | Day-by-day learning log, including every bug I hit and what it taught me. |
| `.env.example` | Template for the environment variables. Copy to `.env`. |

---

## Stretch goals

All three completed:

- [x] **Streaming** — replies print word by word as they arrive. Toggle with
      `/stream` or start with `--no-stream`. Token usage still comes back intact,
      it just arrives on the final chunk. Streaming changes perceived speed, not
      cost.
- [x] **`--model` flag** — switch models from the command line, overriding `.env`.
      Plus `--list-models` to see what your key can reach.
- [x] **Persona library** — five system prompts (`tutor`, `pirate`, `teacher`,
      `terse`, `rubberduck`), switchable mid-conversation with `/persona`.

The persona library produced the most interesting result in the project. Asking
`What is 15 + 27?` under three personas gave an **87x spread in output tokens**:

| Persona | Reply | Output tokens | Cost |
| --- | --- | --- | --- |
| `pirate` | A tobacco-spitting rant, then concedes **42** | 175 | $0.000450 |
| `teacher` | Refuses to answer, asks a guiding question instead | 55 | $0.000206 |
| `terse` | `42` | 2 | $0.000093 |

Better still, after switching from `pirate` to `teacher`, the teacher opened with
*"Put that cutlass away this instant."* No cutlass had been mentioned to the
teacher — the pirate had brought one up two turns earlier. Switching persona
replaces the system instruction but keeps the history, so that one line
demonstrates the two channels are genuinely separate.

Extras I added that were not required:

- [x] `/stats` command for on-demand session totals
- [x] `/help` command
- [x] Colour-coded output that automatically disables itself when piped to a file
- [x] A pricing table covering several models, with a warning when the selected
      model has no rates on file
- [x] Rollback of history on a failed request
