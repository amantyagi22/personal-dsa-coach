# Personal DSA Coach

A local-first CLI that tells you which **one** LeetCode problem to solve today, and why.

Most DSA practice is undirected — you re-solve the patterns you're already good at and quietly avoid the ones you aren't.
This coach reads your real LeetCode history, works out where you're actually weak, and picks a single problem each morning with an explanation you can argue with.

> **Status:** early development. The design is settled and specced; the code is being built milestone by milestone.
> See [issue #1](https://github.com/amantyagi22/personal-dsa-coach/issues/1) for the full spec and the [open issues](https://github.com/amantyagi22/personal-dsa-coach/issues) for the build plan.

## What it does

```bash
python -m app.cli today            # which ONE problem should I solve today, and why
python -m app.cli analyze <url>    # analyse a problem: pattern, algorithm, recognition clues
python -m app.cli attempt <id>     # log how an attempt went (including *how* you failed)
python -m app.cli review           # get quizzed on a past problem, solution withheld
python -m app.cli stats            # pattern mastery, streak, weak spots
python -m app.cli sync             # import your real LeetCode submission history
python -m app.cli ask "..."        # ask anything, answered against your own history
```

The daily recommendation looks like this:

```text
Today's Problem

Longest Repeating Character Replacement

Difficulty: Medium
Pattern: Sliding Window

Why this problem?

• Your Sliding Window success rate is 50%.
• You struggled with variable-size windows twice.
• You haven't practiced this pattern for 6 days.
• This problem is appropriate for your current difficulty.
• You have already solved simpler Sliding Window problems.

Recommended time: 30 minutes.
```

Every one of those reasons is a real number computed from your history — not generated prose.

## How it works

Two ideas do most of the work.

**Deterministic logic and LLM reasoning are strictly separated.**
Python computes every number: success rates, weak patterns, review dates, recommendation scores, streaks.
The LLM does what only a language model can: understanding problems, identifying patterns, explaining algorithms, spotting conceptual similarity, and grading your free-text answers.
The model never calculates a statistic, and the recommendation is always `max(score)` chosen by Python.

**The agent loop is written by hand.**
No LangChain, no `create_agent`. The loop prompts the model, receives tool calls, validates arguments, executes Python functions, feeds results back, and repeats until the model produces a final answer. Understanding that loop is half the point of the project.

```text
User → Agent → LLM decides what it needs → Tool call → Python executes
                  ↑                                         ↓
                  └──────────── Tool result ←───────────────┘
                                    ↓
                             Final response
```

**Tracking *how* you failed is what makes the recommendations useful.**
Five outcomes are distinguished: couldn't identify the pattern, identified it but couldn't derive the algorithm, derived it but the implementation failed, correct but too slow, and correct.
Repeatedly failing to *recognise* Sliding Window calls for simpler recognition practice; repeatedly recognising it and botching the implementation calls for something else entirely.

## Setup

**Requirements:** Python 3.12+, a Gemini API key (free tier is fine), and optionally a LeetCode account.

```bash
git clone git@github.com:amantyagi22/personal-dsa-coach.git
cd personal-dsa-coach

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .

cp .env.example .env               # then edit .env — see below
```

### Configuration

Edit `.env`:

| Variable | Required | What it's for |
|---|---|---|
| `GEMINI_API_KEY` | yes | Get one free at [Google AI Studio](https://aistudio.google.com/apikey) |
| `GEMINI_MODEL_REASONING` | yes | Stronger model, used for problem analysis and grading review answers |
| `GEMINI_MODEL_FAST` | yes | Cheaper model, used for the agent loop, `ask`, and recommendation prose |
| `LEETCODE_SESSION` | no | Session cookie — only needed to import your submission history |

Two models rather than one because the free tier gives the Pro-tier models far fewer requests per day than Flash.
Analysis quality matters, so Pro handles it; the mechanical agent-loop steps run on Flash, which means `today` keeps working even after your Pro quota is exhausted.

### Importing your LeetCode history (optional but recommended)

Without this, the coach starts cold and gives you a sensible default until you've logged a few attempts. With it, you get real pattern statistics on day one.

1. Log in to leetcode.com in your browser
2. Open DevTools → Application → Cookies → `https://leetcode.com`
3. Copy the value of `LEETCODE_SESSION` into your `.env`
4. Run `python -m app.cli sync`

> ⚠️ **`LEETCODE_SESSION` is a full-access credential for your LeetCode account.**
> Anyone holding it is logged in as you. It belongs in `.env` (which is gitignored) and nowhere else.
> The cookie expires every couple of weeks — re-paste it when sync starts failing.
>
> Sync is always an explicit command, never automatic, so an expired cookie means "your history is a few days stale", not "your daily recommendation is broken".

### First run

```bash
python -m app.cli sync-problems    # fetch the LeetCode problem catalogue (~4,000 problems)
python -m app.cli sync             # import your submission history (needs the cookie)
python -m app.cli today            # get your first recommendation
```

## Running the tests

```bash
pytest
```

The tests run with **no API key and no network access**.
The recommendation engine is a plain Python class with no LLM dependency, and every agent test drives a fake provider — so scoring logic, the agent loop's safety behaviour, and all statistics are verifiable offline.

## Design decisions worth knowing

- **Problems come from LeetCode's public GraphQL API**, not a bundled dataset — 4,028 problems with tags and difficulty, no authentication needed, never stale.
- **No vector database.** Similarity is SQLite FTS5 for retrieval plus the LLM for judging conceptual likeness. The corpus is a few hundred problems — far below where a vector index earns its cost. There's room in the schema to add embeddings later if recall proves insufficient.
- **Editorial solutions are deliberately excluded.** The goal is teaching you to *recognise* patterns, not to summarise someone else's answer.
- **Unclassified attempts are excluded from scoring**, never treated as average — an unlabelled backlog shouldn't quietly drag every statistic toward the mean.
- **The LLM provider is abstracted**, so Ollama or OpenAI can be added later without rewriting the agent.

## Cost

Zero. The Gemini free tier covers everything, and the LeetCode API is public.

One thing to know: **Gemini's free tier uses submitted prompts for model training** (the paid tier and Vertex AI do not). For this project that means problem text, generated analyses, and your practice history. It's a deliberate trade for zero cost on public problems and personal practice data — but it should be a choice, not a surprise.

## Project structure

```text
app/
├── agent/        # tool registry, the hand-written loop, prompts, schemas
├── llm/          # LLMProvider interface + GeminiProvider
├── problems/     # LeetCode API client and problem services
├── learning/     # mastery, recommender, spaced review
├── storage/      # SQLite models and repositories
├── api/          # FastAPI routes (thin — no business logic)
├── scheduler/    # daily recommendation job
└── cli.py
```

The CLI, the web API, and the scheduler are three thin adapters over one set of application services. Business logic lives in exactly one place.

## Licence

Personal project, no licence specified.
