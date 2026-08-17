# Architecture

How the Personal DSA Coach is put together, and why.

This document explains the design decisions behind the code.
For installation and usage, see the [README](../README.md). For the full requirements, see [the spec](https://github.com/amantyagi22/personal-dsa-coach/issues/1).

---

## The core idea

The project has two goals that pull in opposite directions:

1. **Build something genuinely useful** - a coach whose recommendations you can trust.
2. **Learn how AI agents actually work** - by writing the agent loop by hand, not calling a framework.

Trustworthy recommendations mean the numbers can't be hallucinated.
Learning about agents means the LLM has to make real decisions.

The resolution is a strict split:

> **Python computes. The LLM reasons. The LLM decides *what it needs to look at*, but never calculates anything.**

Concretely:

| Python does this | The LLM does this |
|---|---|
| Success rates, mastery percentages | Understanding a problem statement |
| Weak-pattern detection | Identifying which DSA pattern applies |
| Recommendation scoring and ranking | Explaining an algorithm and its complexity |
| Review scheduling | Judging whether two problems are conceptually similar |
| Streaks, averages, distributions | Grading your free-text review answers |
| Selecting the single winning problem | Explaining *why* that problem was chosen |

If the coach says "your Sliding Window success rate is 50%", that number came from a SQL query, not from a model.

---

## The agent loop

This is the heart of the project, and it's written by hand - no LangChain, no `create_agent`.

```text
   User request
        │
        ▼
   ┌─────────┐
   │  Agent  │◄────────────────────────┐
   └────┬────┘                         │
        │ prompt + available tools     │
        ▼                              │
   ┌─────────┐                         │
   │   LLM   │  "I need the problem"   │
   └────┬────┘                         │
        │ tool call                    │
        ▼                              │
   validate arguments                  │
        │                              │
        ▼                              │
   execute Python function             │
        │                              │
        └──── tool result ─────────────┘
        │
        │ (repeat until the model stops asking for tools)
        ▼
   Final response
```

Each turn: prompt the model, receive tool calls, validate the arguments, execute the Python function, feed the result back, repeat.
The model chooses *which* tools to call and in *what order* - that's the agency. It might check review-due problems before weak patterns, or the reverse.

### Why this matters for `today`

`today` looks like a report generator, but it's a real agent.
The LLM decides what information it needs and calls deterministic tools to get it. Python still computes every score and picks the winner with `max(score)`. The LLM's final job is to explain a decision that was already made.

**Agency is over information gathering, not arithmetic.** That's what lets the tool be both a genuine agent and a trustworthy recommender.

### Loop safety

Three mechanisms, all of which double as cost controls (see [Rate limits](#rate-limits-shape-everything)):

- **Per-command iteration cap.** A deep `analyze` and a quick `ask` need different budgets, so this is configurable per command rather than one global constant.
- **Per-turn result cache.** If the model asks for the same thing twice in one turn, the second call is served from cache. Keyed on tool name plus arguments, cleared between turns.
- **Repetition guard.** After N identical calls, the loop tells the model to answer with what it has. It doesn't crash - a slightly truncated real answer beats a stack trace.

**Write tools are never cached.** Caching a save would silently swallow a legitimate second write.

### The `read_only` flag

Every tool declares whether it's read-only. That single flag does two jobs:

1. **Caching** - only read-only results are cacheable.
2. **Permissions** - `ask` is given the read-only tools *only*, so asking a question can never modify your learning history as a side effect.

---

## The three agent surfaces

| Command | Tools it can use | Model | Why |
|---|---|---|---|
| `ask` | read-only | fast | Conversational, used casually, must never mutate data |
| `analyze` | read-only | reasoning | Quality matters most here - this is what you learn from |
| `today` | read-only | fast | Run every day; must keep working when the stronger model's quota is gone |

**Every tool is read-only, which is a change from the original design.** The plan
gave `analyze` a `save_problem_analysis` tool and `today` a save-recommendation
tool. Implementing `analyze` made the alternative look better: the service calls
the model, validates the result against a Pydantic schema, and *then* writes it
in Python.

That means a write cannot happen unless the output validated, the write cannot
happen twice, and an interrupted run leaves no partial record. It also fits the
project's central rule more closely than a save tool would - the model reasons,
Python decides what to persist.

The `read_only` flag has not become decoration. It still governs the per-turn
cache, and it is the mechanism that will keep `ask` read-only if a write tool is
ever added.

---

## Data

### Where problems come from

LeetCode's **public GraphQL API** - no authentication, no bundled dataset.

- The catalogue query returns **4,028 problems** with difficulty, topic tags, and paid-only flags
- A separate query returns any problem's full description on demand

A static dataset (Kaggle, GitHub dumps) was considered and rejected: the live API is more complete, never goes stale, and carries no licensing questions.

**Editorial solutions are deliberately not fetched.** The goal is teaching you to *recognise* patterns. Feeding the agent someone else's solution makes it summarise rather than teach.

### Where your history comes from

Your **real LeetCode submissions**, imported by `sync` using a session cookie.

This solves the cold-start problem: without it, the coach knows nothing about you until you've manually logged twenty attempts. With it, you have genuine pattern statistics on day one.

> **One critical safety behaviour:** when the session cookie is invalid, LeetCode's API returns `null` for the submission list rather than an error. Sync must treat that as *"your cookie expired"* and write nothing. Treating it as *"you have no submissions"* would silently wipe real learning history.

Sync is always an explicit command, never automatic - so an expired cookie means "your history is a few days stale", not "your daily recommendation is broken".

### Patterns

Around 25 canonical patterns (Sliding Window, Two Pointers, Binary Search, DP, …) stored as **data in a table**, not a hard-coded list, so the vocabulary stays editable.

LeetCode's topic tags are an unordered bag - a problem tagged `Hash Table, String, Sliding Window` doesn't say which is primary. Two stages resolve this:

1. **A deterministic priority-ordered mapping** picks the primary from the tags. This classifies all 4,028 problems instantly with zero AI cost.
2. **When you `analyze` a problem, the LLM's judgement overrides it** and is stored as authoritative from then on.

A `pattern_source` column records which method produced each classification, so mixed data is visible rather than hidden.

### Failure types

The most important thing this tool tracks. Five outcomes:

| | Outcome |
|---|---|
| **A** | Couldn't identify the pattern |
| **B** | Identified the pattern, couldn't derive the algorithm |
| **C** | Derived the algorithm, implementation failed |
| **D** | Correct, but too slow |
| **E** | Correct |

These lead to completely different recommendations. Repeatedly failing to *recognise* Sliding Window means you need simpler recognition practice; recognising it every time and botching the implementation means you need something else entirely.

**Sync can only infer D and E.** From the outside, A, B, and C are indistinguishable - and A and B usually produce *zero* submissions, because you never got far enough to submit. Only you can supply them, via `attempt`.

Unclassified attempts are stored as `unknown` and **excluded from failure-driven scoring** - never treated as an average. Otherwise an unlabelled backlog would quietly drag every statistic toward the mean.

---

## The recommendation engine

A plain Python class. No LLM, no network, no CLI - which is exactly why it's the most thoroughly tested part of the system.

It generates candidates, scores them, and returns a ranked list with a breakdown per component:

| Component | Weight |
|---|---|
| Pattern weakness | 30% |
| Review due | 25% |
| Difficulty fit | 20% |
| Time since practice | 10% |
| Similarity | 10% |
| Variety | 5% |

All weights are configurable.

### Handling missing data

The interesting design decision. On day one there are no attempts, so pattern weakness has nothing to say. A newly encountered pattern has no history either.

Rather than special-casing "cold start", **each component declares whether it has enough data to have an opinion, and the weights renormalise across the ones that do.**

- **No history at all** → only difficulty fit and variety contribute → an Easy problem from a foundational pattern, and the output says plainly that there's nothing to personalise from yet
- **Some history** → components join in as their data arrives
- **A brand-new pattern** → handled by the same mechanism, no extra code

One mechanism, three problems solved.

---

## Similarity without a vector database

Finding "conceptually similar problems" normally means embeddings and a vector store. This project doesn't use one.

**Retrieval** uses SQLite's built-in full-text search (FTS5) plus structured filters on pattern and difficulty. FTS5 ships inside Python's standard library - no extra dependency, no service, no cost.

**Judgement** is the LLM's. Given ~20 retrieved candidates, it decides which are genuinely conceptually similar.

### Why no vectors

Hosted Postgres with pgvector has real free tiers, so cost wasn't the blocker. Two other things were:

- It breaks local-first operation - `today` should work on a plane
- **The corpus is 4,028 problems, and the part that matters is far smaller.** Similarity only ever searches problems you have *analysed*, which is dozens, not thousands. Vector indexes earn their cost in the tens of thousands. At this size you can hand the model a deliberately wide candidate set and let it read all of them, which compensates for keyword search's weaker recall

If recall ever proves insufficient, the upgrade is small: an `embedding` column on the problems table and cosine similarity in numpy. The schema already leaves room. That's deliberately deferred until the problem is observed rather than assumed.

---

## The LLM provider abstraction

Nothing outside the provider package imports the Gemini SDK.

`LLMProvider` exposes three capabilities:

1. **Free-form generation** - plain text in, plain text out
2. **Schema-constrained generation** - returns data matching a Pydantic model
3. **Tool calling** - the agent loop's foundation

The second one carries a design decision worth naming. Getting reliable JSON out of a model can be done two ways: ask nicely and parse-and-retry, or use the provider's native schema enforcement. Gemini has the latter; a local Ollama model doesn't.

**So structured output is the *provider's* responsibility, not the caller's.** `GeminiProvider` uses native `response_schema`; a future `OllamaProvider` would use prompt-and-parse behind the same interface. Callers never know the difference, and the retry logic isn't duplicated everywhere.

Pydantic models are the single source of truth - schemas are never written twice.

### Two models

| Setting | Used for |
|---|---|
| `GEMINI_MODEL_REASONING` | Problem analysis, grading review answers |
| `GEMINI_MODEL_FAST` | Agent loop, `ask`, recommendation prose |

The free tier gives the stronger models roughly 50–100 requests/day versus ~1,500 for the fast ones. An agentic `today` run is several round-trips. Putting the loop on the fast model means your daily driver keeps working even when the stronger quota is exhausted.

---

## Rate limits shape everything

Worth stating directly, because it explains several decisions that would otherwise look like premature optimisation:

- **Per-role models** - spend scarce quota only where quality matters
- **Per-turn tool caching** - never pay twice for the same lookup
- **Per-command iteration caps** - bound the cost of a single command
- **The repetition guard** - a stuck model can't burn the day's quota

These are cost controls as much as correctness controls.

---

## Layers

```text
    CLI ──────────┐
                  │
    Web API ──────┼──→ Application Services
                  │            │
    Scheduler ────┘            ▼
                            Agent
                              │
                              ▼
                            Tools
                              │
                              ▼
                          Database
```

The CLI, the REST API, and the scheduler are three **thin adapters** over one set of application services.

This matters more than it sounds. If a rule about how attempts get recorded lives inside a CLI command, the API will silently disagree with it. Business logic lives in exactly one place, and the adapters only translate.

```text
app/
├── agent/        # tool registry, the loop, prompts, schemas
├── llm/          # LLMProvider interface + GeminiProvider
├── problems/     # LeetCode API client, problem services
├── learning/     # mastery, recommender, spaced review
├── storage/      # SQLite models and repositories
├── api/          # FastAPI routes (thin)
├── scheduler/    # daily recommendation job
└── cli.py
```

---

## Testing

Tests assert **external behaviour**, never implementation details. A test should describe something a caller cares about, and survive a rewrite of the internals underneath it.

Three seams carry the weight:

**1. The recommendation engine.** A plain class with no LLM and no network. Feed it fixture histories, assert on the ranking and the reasons. Covers scoring, weight renormalisation, cold start, exclusions, and review-due logic. Most of the test value lives here.

**2. The LLM provider.** Every agent test injects a fake provider returning scripted tool calls. This is what makes the loop testable at all - iteration caps, caching, the repetition guard, and the `ask` permission boundary are all verified by driving a fake and asserting which tools ran.

**3. The tool registry.** Tools are plain functions with validated arguments, callable directly against an in-memory database.

**Not seams:** the CLI (a thin wrapper - testing it mostly re-tests the services) and live network calls (covered by fixtures shaped from real responses; real calls happen during manual verification only).

The whole suite runs with no API key and no internet.

---

## Deliberately not built

- **Vector search** - deferred; the schema has room
- **Hosted databases of any kind** - this stays local-first
- **Any agent framework** - the hand-written loop is the point
- **Telegram / Discord / email notifications** - the interface allows them, only console is implemented
- **Ollama / OpenAI providers** - the abstraction permits them, neither is built
- **Docker, authentication, multi-user** - single local user
- **Automatic sync** - always explicit, so an expired cookie is never mistaken for an empty history
