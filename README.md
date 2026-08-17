# Personal DSA Coach

A command-line coach that tells you which **one** LeetCode problem to solve today, and why.

Most DSA practice is undirected. You re-solve the patterns you're already comfortable with and quietly avoid the ones you aren't - so you never find out that your Sliding Window success rate is 50% while your DFS is 89%.

This tool reads your real LeetCode history, works out where you're actually weak, and picks a single problem each morning with an explanation you can argue with.

> **Status:** early development. The design is finished; the code is being built step by step.
> Milestone 1 is done - configuration, the Gemini provider, and `ask` work today. Every other command below is still being built.
> See [the spec](https://github.com/amantyagi22/personal-dsa-coach/issues/1) and the [build plan](https://github.com/amantyagi22/personal-dsa-coach/issues).

## What you get

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

Every reason there is a real number from your own history - not something an AI made up.

## Commands

| Command | What it does | |
|---|---|---|
| `ask "..."` | Ask anything, answered against your own history | ✅ working |
| `today` | Which one problem should I solve today, and why | planned |
| `analyze <url>` | Break down a problem: pattern, algorithm, how to recognise it next time | planned |
| `attempt <id>` | Log how an attempt went - including *how* you failed | planned |
| `review` | Get quizzed on a past problem, solution withheld until you answer | planned |
| `stats` | Pattern mastery, streak, strongest and weakest areas | planned |
| `sync` | Import your real LeetCode submission history | planned |

Run any of them as `python -m app.cli <command>`.

Today `ask` is a plain question-answerer. Once the database and the tool registry exist it is upgraded in place to answer against your own practice history.

## Setup

You'll need **Python 3.12+** and a **free Gemini API key**. A LeetCode account is optional but makes the tool much more useful straight away.

### 1. Install

```bash
git clone git@github.com:amantyagi22/personal-dsa-coach.git
cd personal-dsa-coach

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # drop [dev] if you don't want to run the tests
```

### 2. Add your Gemini key

Get a free key at [Google AI Studio](https://aistudio.google.com/apikey), then:

```bash
cp .env.example .env
```

Open `.env` and paste your key in. There are two model settings alongside it, already filled in with sensible defaults:

| Setting | What it's for |
|---|---|
| `GEMINI_API_KEY` | Your key |
| `GEMINI_MODEL_REASONING` | The stronger model - used for analysing problems and grading your answers |
| `GEMINI_MODEL_FAST` | The cheaper model - used for everything else |
| `LEETCODE_SESSION` | Optional. Only needed to import your LeetCode history |

Two models because the free tier allows far fewer requests per day on the stronger one. The tool spends it where quality actually matters and uses the cheap model elsewhere, so your daily recommendation keeps working even if you run out.

### 3. Connect your LeetCode account (optional)

Skip this and the tool still works - it just starts with no knowledge of you and gives sensible defaults until you've logged a few attempts.

With it, you get real pattern statistics on day one.

1. Log in to leetcode.com in your browser
2. Open DevTools → Application → Cookies → `https://leetcode.com`
3. Copy the value of `LEETCODE_SESSION` into your `.env`

> ⚠️ **That cookie is full access to your LeetCode account.** Anyone who has it is logged in as you.
> Keep it in `.env` (which is never committed) and nowhere else. It expires every couple of weeks - just paste a fresh one when `sync` starts failing.

### 4. First run

```bash
python -m app.cli ask "Explain sliding window"
```

If you get a real answer back, everything is wired up correctly. Add `-v` to see which model each call uses.

Once the later milestones land, first run will also include:

```bash
python -m app.cli sync-problems    # download the problem catalogue (~4,000 problems)
python -m app.cli sync             # import your history (needs the cookie from step 3)
python -m app.cli today            # your first recommendation
```

## Running the tests

```bash
pytest
```

The tests need **no API key and no internet**.

## Cost

Free. The Gemini free tier covers everything and the LeetCode data is public.

One thing worth knowing: **Google's free tier uses what you send it to train their models** (their paid tier doesn't). Here that means problem text, the analyses generated for you, and your practice history. It's a fair trade for a zero-cost personal tool on public problems - but you should know it rather than find out later.

## How it works

Two ideas do most of the work:

**Python does the maths, the AI does the thinking.** Success rates, weak patterns, review dates, and recommendation scores are all calculated in plain Python - so the numbers are correct and reproducible. The AI handles what only a language model can: understanding problems, spotting patterns, explaining algorithms, and grading your written answers. It never calculates a statistic.

**It tracks *how* you failed, not just whether you failed.** "Couldn't spot the pattern" and "spotted it but botched the code" are completely different problems that need completely different next steps. Most tools record neither.

For the full picture - the agent loop, the data model, the scoring engine - see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Licence

Personal project, no licence specified.
