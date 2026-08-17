# Spec: Personal DSA Coach AI Agent

## Problem Statement

I practice data structures and algorithms on LeetCode, but my practice is undirected.
I pick problems more or less at random, or by working down a list someone else wrote.

The result is that I keep re-solving the patterns I am already comfortable with, and quietly avoid the ones I am not.
I have no way of knowing that my Sliding Window success rate is 50% while my DFS success rate is 89%, so I cannot act on it.

Worse, when I fail a problem I do not record *how* I failed.
"Could not identify the pattern" and "identified the pattern but botched the implementation" are completely different problems that call for completely different next problems, and both are currently recorded the same way: not at all.

I also forget.
A pattern I understood well six weeks ago has decayed, and nothing tells me it is due for review.

Finally, I am a backend engineer who wants to understand how AI agents actually work.
Reading about tool-calling loops has not given me the understanding that building one would.

## Solution

A local-first command-line coach that knows my DSA history and tells me which single problem to solve today, with an explanation I can argue with.

Every morning I run one command and get one problem, plus the reasoning: which pattern it trains, why that pattern is weak for me, how long since I last practiced it, and how it fits my current difficulty level.
The recommendation is deterministic and explainable — Python computes the score, and the LLM only puts the result into words.

When I hit a problem I do not understand, I analyze it.
The agent fetches the problem, identifies the primary pattern and secondary techniques, explains the algorithm and complexity, and — most importantly — tells me **how to recognize this pattern in future problems**.
It searches my own previously analyzed problems for conceptually similar ones, so new knowledge attaches to old knowledge.

My learning history seeds itself from my real LeetCode account, so the coach is useful on day one rather than after a month of manual logging.
What LeetCode cannot know — whether I identified the pattern, whether I used a hint, what actually went wrong — I supply myself, in a batch, when I feel like it.

Under the hood, the agent loop is written by hand.
The LLM decides which tools it needs and in what order; Python executes them and computes every number.
Nothing is hidden behind a framework abstraction, because understanding that loop is half the point of the project.

## User Stories

### Analyzing a problem

1. As a learner, I want to analyze a LeetCode problem by pasting its URL, so that I can understand it without hunting through editorials.
2. As a learner, I want the agent to fetch the problem statement automatically, so that I do not have to copy and paste it.
3. As a learner, I want the primary DSA pattern identified, so that I know what family of technique this problem belongs to.
4. As a learner, I want secondary techniques listed, so that I understand what else the problem combines.
5. As a learner, I want an explanation of *why* that pattern applies, so that the classification is arguable rather than asserted.
6. As a learner, I want the key observation that unlocks the problem stated explicitly, so that I can look for similar observations in future problems.
7. As a learner, I want a step-by-step algorithm explanation, so that I can follow the reasoning rather than memorize code.
8. As a learner, I want time and space complexity explained, so that I understand the cost of the approach.
9. As a learner, I want a list of concrete recognition clues, so that I can spot this pattern in an unseen problem.
10. As a learner, I want common mistakes for this problem listed, so that I can avoid them before making them.
11. As a learner, I want conceptually similar problems from my own history surfaced, so that new knowledge attaches to what I already know.
12. As a learner, I want the analysis saved to my knowledge base, so that it is searchable later and feeds future recommendations.
13. As a learner, I want to re-analyze a problem I have already analyzed, so that I can get a fresh explanation when my understanding has changed.
14. As a learner, I do NOT want editorial solutions pulled into the analysis, so that the agent teaches me recognition rather than summarizing someone else's answer.

### The daily recommendation

15. As a learner, I want one problem recommended each day, so that I do not waste willpower choosing.
16. As a learner, I want exactly one problem rather than a list, so that I cannot cherry-pick the easy option.
17. As a learner, I want the recommendation to be explainable, so that I can tell whether the coach's reasoning is sound.
18. As a learner, I want my weakest patterns weighted most heavily, so that practice goes where it is most needed.
19. As a learner, I want problems due for spaced review to be surfaced, so that old knowledge does not decay silently.
20. As a learner, I want difficulty matched to my demonstrated level, so that I am stretched but not crushed.
21. As a learner, I want time-since-last-practice considered, so that neglected patterns resurface.
22. As a learner, I want variety enforced, so that I am not given five sliding-window problems in a row.
23. As a learner, I want recently solved problems excluded, so that I am not handed something I just finished.
24. As a learner, I want a problem I am *due to review* to be recommendable even though I solved it before, so that spaced repetition actually works.
25. As a learner, I want my repeated mistakes to influence the recommendation, so that a pattern I keep failing the same way gets targeted practice.
26. As a learner, I want a recommended time budget, so that I know when to stop and look at the solution.
27. As a learner, I want the recommendation saved, so that I have a record of what was suggested and why.
28. As a learner, I want a sensible recommendation on my very first run with no history, so that the tool is useful before I have fed it anything.
29. As a learner, I want the coach to tell me plainly when it has too little data to personalize, so that I am not misled by confident-sounding but ungrounded advice.
30. As a learner, I want the scoring weights to be configurable, so that I can tune the coach to my own priorities.

### Learning history and sync

31. As a learner, I want to import my real LeetCode submission history, so that the coach is useful from day one.
32. As a learner, I want sync to be an explicit command rather than automatic, so that a stale session cookie never silently breaks my daily recommendation.
33. As a learner, I want sync to fail loudly when my session cookie has expired, so that I never mistake an auth failure for an empty history.
34. As a learner, I want accepted submissions recorded as successes automatically, so that I do not have to log what LeetCode already knows.
35. As a learner, I want time-limit-exceeded submissions recorded as "correct but too slow" automatically, so that a distinct failure mode is captured for free.
36. As a learner, I want to see which attempts came from LeetCode and which I logged myself, so that I can trust the provenance of my own statistics.
37. As a learner, I want my session cookie kept out of version control, so that I never leak full access to my LeetCode account.

### Logging attempts

38. As a learner, I want to log an attempt against a problem, so that the coach learns from outcomes it cannot observe.
39. As a learner, I want to record whether I identified the correct pattern, so that pattern-recognition failures are distinguished from implementation failures.
40. As a learner, I want to record whether I used a hint, so that a solve with help is not counted the same as a solve without.
41. As a learner, I want to record how long the attempt took, so that speed is tracked alongside correctness.
42. As a learner, I want to classify how I failed using a fixed set of failure types, so that the coach can act on the distinction.
43. As a learner, I want to write free-text notes about what went wrong, so that I capture nuance the categories miss.
44. As a learner, I want the agent to suggest a failure type from my notes, so that classification is fast — but I want the final say, so that my history is never silently wrong.
45. As a learner, I want to be told when attempts are missing a failure type, so that I can fill them in when convenient rather than being nagged after every problem.
46. As a learner, I do NOT want unclassified attempts treated as average, so that an unlabeled backlog does not quietly drag every statistic toward the mean.

### Review mode

47. As a learner, I want to be quizzed on a previously studied problem, so that I find out whether I actually retained it.
48. As a learner, I want the solution withheld until I have answered, so that I cannot fool myself into thinking I remembered.
49. As a learner, I want to be asked which pattern applies and why, so that recognition is tested rather than recall of code.
50. As a learner, I want to be asked what algorithm I would use and its complexity, so that the whole reasoning chain is exercised.
51. As a learner, I want my free-text answer evaluated, so that I get feedback rather than a self-graded guess.
52. As a learner, I want the evaluation recorded, so that review outcomes feed back into scheduling.
53. As a learner, I want failed reviews scheduled sooner than successful ones, so that weak knowledge gets more attention.
54. As a learner, I want review intervals to be configurable, so that I can adjust the schedule to my own retention.

### Conversational coaching

55. As a learner, I want to ask the coach open questions in natural language, so that I can explore a topic without a rigid command.
56. As a learner, I want answers grounded in my own history, so that "explain sliding window" tells me about *my* sliding window weaknesses.
57. As a learner, I want the conversational command to be read-only, so that asking a question never mutates my learning history.
58. As a learner, I want the conversational command to run on the cheaper model, so that casual questions do not exhaust my daily quota for real analysis.

### Statistics

59. As a learner, I want to see problems solved and attempted, so that I have a sense of volume.
60. As a learner, I want to see my current streak, so that I have a reason to keep going.
61. As a learner, I want average solve time, so that I can track speed as well as correctness.
62. As a learner, I want a pattern mastery table with attempts, successes, and success rate, so that I can see my profile at a glance.
63. As a learner, I want my strongest and weakest patterns called out, so that I do not have to read the whole table.
64. As a learner, I want patterns due for review listed, so that I know what is decaying.
65. As a learner, I want a difficulty distribution, so that I can see whether I am avoiding hard problems.
66. As a learner, I want all statistics computed by deterministic Python, so that the numbers are reproducible and never hallucinated.

### Agent mechanics

67. As a developer, I want to write the tool-calling loop myself, so that I understand how agents actually work.
68. As a developer, I want the loop's steps visible in logs, so that I can watch the LLM decide what it needs.
69. As a developer, I want the LLM to choose which tools to call rather than following a hard-coded sequence, so that the system exhibits genuine agent behavior.
70. As a developer, I want all statistics and scoring kept outside the LLM, so that numbers are reliable and testable.
71. As a developer, I want a maximum iteration limit per command, so that a confused model cannot loop indefinitely.
72. As a developer, I want the iteration limit configurable per command, so that a deep analysis and a quick question can have different budgets.
73. As a developer, I want repeated identical tool calls within a turn served from cache, so that quota is not wasted re-fetching the same data.
74. As a developer, I want write-tools excluded from caching, so that a second legitimate write is never silently swallowed.
75. As a developer, I want a repetition guard that ends the turn with a real answer when the model gets stuck, so that I get a degraded answer rather than a stack trace.
76. As a developer, I want tool arguments validated before execution, so that a malformed model output fails clearly.
77. As a developer, I want tool errors returned to the model rather than raised, so that the agent can recover and try a different approach.

### Provider abstraction and cost

78. As a developer, I want all LLM access behind one interface, so that the rest of the application never imports Gemini.
79. As a developer, I want to add a local Ollama provider later without rewriting the agent, so that I can eventually run this offline.
80. As a developer, I want structured output to be the provider's responsibility, so that each provider uses its best mechanism rather than every caller re-implementing JSON parsing.
81. As a developer, I want Pydantic models to be the single source of truth for schemas, so that I never write the same schema twice.
82. As a developer, I want a stronger model for analysis and a cheaper one for mechanical work, so that scarce quota goes where quality matters.
83. As a developer, I want the model name logged on every call, so that I can tell which model produced a given output.
84. As a developer, I want rate-limit errors surfaced as clear messages, so that quota exhaustion is obvious rather than mysterious.
85. As a developer, I want the project to cost nothing during development, so that I can build it without a budget.

### Web API and UI

86. As a learner, I want a REST API exposing the same capabilities as the CLI, so that I can build a UI on it.
87. As a developer, I want the API and CLI to share the same application services, so that business logic exists in exactly one place.
88. As a learner, I want a minimal dashboard showing today's problem, weak patterns, recent activity, and streak, so that I can see my state at a glance.
89. As a learner, I want a searchable problem library filtered by pattern, difficulty, and status, so that I can find past analyses.
90. As a learner, I want a progress view showing pattern mastery, so that improvement is visible over time.

### Scheduling

91. As a learner, I want a daily recommendation generated automatically each morning, so that it is waiting for me.
92. As a learner, I want the notification mechanism swappable, so that I can add Telegram or email later without rework.

## Implementation Decisions

### Problem catalogue and ingestion

- **Problems come from LeetCode's public GraphQL endpoint.** Verified during design: the catalogue query returns **4,028 problems** with `questionFrontendId`, `title`, `titleSlug`, `difficulty`, `isPaidOnly`, `acRate`, and `topicTags` — with **no authentication**. A separate query returns full problem `content` (HTML) by slug, also unauthenticated.
- **No bundled problem dataset.** Kaggle and GitHub LeetCode dumps were evaluated and rejected: the live API is more complete (4,028 vs ~2,900), never stale, and carries no licensing ambiguity.
- **Editorial solutions are deliberately excluded** even where available. The product goal is pattern recognition; feeding editorials into context makes the agent summarize a solution rather than teach recognition.
- **Paid-only problems are marked** via `isPaidOnly` so the recommender can avoid recommending problems the user cannot open.
- A `sync-problems` command refreshes the catalogue. `analyze` fetches a single problem's description on demand.

### LeetCode account sync

- **Submission history requires the `LEETCODE_SESSION` cookie**; the catalogue does not. Verified: `submissionList` returns `null` (not an error) when unauthenticated.
- **A `null` submission list must be treated as "cookie expired", never as "no submissions."** Sync must refuse to write anything when it cannot distinguish the two — writing an empty history would destroy real data.
- `recentAcSubmissionList` works unauthenticated given a public username and is available as a degraded fallback (accepted submissions only).
- **Sync is an explicit command, never implicit.** An expired cookie means "your history is N days stale", not "your daily recommendation is broken."
- The cookie is a full-access credential: it lives in `.env`, never in `.env.example`, and `.gitignore` covers it from the first commit.

### Pattern taxonomy

- **~25 canonical patterns** are seeded as data in the `patterns` table, not as a hard-coded enum, so the vocabulary is editable.
- **LeetCode's topic tags are an unordered bag** — a problem tagged `Hash Table, String, Sliding Window` has no declared primary. A deterministic **priority-ordered mapping** collapses the bag to one primary pattern, so the entire 4,028-problem catalogue is classified instantly with no LLM cost.
- **Gemini's judgment overrides the tag-derived primary during `analyze`**, and the override is stored as authoritative from then on.
- A `pattern_source` column records `tags` or `llm` per problem, so mixed-provenance data is visible rather than hidden.

### Recommendation engine

- `RecommendationEngine` is a **plain Python class with no LLM dependency**. It generates candidates deterministically, scores them, and returns a ranked list with per-component breakdowns.
- Initial weights (configurable): `pattern_weakness` 30%, `review_due` 25%, `difficulty_fit` 20%, `time_since_practice` 10%, `similarity` 10%, `variety` 5%.
- **Each scoring component declares whether it has enough data to have an opinion, and weights renormalize across the components that do.** This single mechanism handles the cold start, partial data, and a never-attempted pattern — rather than three special-cased code paths.
- With no history at all, only `difficulty_fit` and `variety` contribute, producing an Easy problem from a foundational pattern, with the absence of data stated plainly in the output.
- **Gemini never scores or ranks candidates.** It explains the already-chosen winner.

### Failure-type model

- Five failure types are tracked: (A) could not identify the pattern, (B) identified but could not derive the algorithm, (C) derived but implementation failed, (D) correct but too slow, (E) correct.
- **Sync can only infer D (TLE) and E (accepted).** A, B, and C are indistinguishable from outside — A and B typically produce *zero* submissions, because the user never got far enough to submit.
- Unresolved attempts are stored as `unknown` and **excluded from failure-type-driven scoring**, never treated as a neutral middle value.
- `stats` and `today` surface a count of attempts needing classification, so backlog is visible without being nagging.
- Gemini may *suggest* a failure type from free-text notes during `attempt`; the user confirms, and the stored value is always the user's choice.

### Agent architecture

- **The tool-calling loop is hand-written.** No LangChain, no `create_agent`. The loop is: prompt → model returns tool calls → validate arguments → execute → return results → repeat until the model returns a final answer.
- **Three agent surfaces with distinct tool allowlists:**
  - `ask` — conversational, **read-only tools only**. A question must never mutate history.
  - `analyze` — read tools plus `save_problem_analysis`.
  - `today` — read tools plus `save_recommendation`.
- **`today` is genuinely agentic**: the model chooses which deterministic tools to call and in what order, while Python computes every number and selects `max(score)`. Agency is over *information gathering*, not arithmetic — which satisfies both the "build a real agent" and "keep business logic deterministic" requirements.
- Each tool declares a `read_only` flag. **That single flag drives two behaviors**: which tools `ask` may call, and which results are cacheable.
- **Per-turn result cache** keyed on `(tool_name, frozen_args)`, cleared between turns, applied to read-only tools only.
- **Per-command iteration cap** — a single global constant would be wrong for both a deep `analyze` and a quick `ask`.
- **Repetition guard** (configurable, default 3 identical calls) injects an instruction to answer with what it has, rather than raising. A truncated real answer beats a stack trace. The guard counts *identical* calls only, so legitimate multi-step traces with varying arguments are never cut off.

### LLM provider interface

- `LLMProvider` exposes three capabilities: free-form generation, **schema-constrained generation**, and tool-calling. Structured output is the *provider's* responsibility, not the caller's.
- `GeminiProvider` implements schema-constrained generation using Gemini's native `response_schema` and native function-calling. A future `OllamaProvider` implements the same interface with prompt-and-parse-and-retry. Callers never know the difference.
- **Pydantic models are the single source of truth.** Provider implementations derive request schemas from them; schemas are never hand-written twice.
- **Per-role model selection:** `GEMINI_MODEL_REASONING` (Pro-tier) for problem analysis and review-answer evaluation; `GEMINI_MODEL_FAST` (Flash-tier) for the agent loop, `ask`, and recommendation prose.
- Rationale: free-tier Gemini gives Pro-tier models roughly 50–100 requests/day versus Flash's ~1,500. An agentic `today` run is several round-trips; putting the loop on Flash keeps `today` working even when Pro quota is exhausted.
- Rate-limit (429) responses surface as an actionable message naming the exhausted model, not a retry storm.
- The model name is logged on every call.

### Similarity

- **No vector database and no embeddings.** Hosted Postgres with pgvector was evaluated (free tiers exist on Neon, Supabase, and Aiven) and rejected: it breaks local-first operation and adds an account dependency, and the corpus is a few hundred rows — far below where a vector index earns its cost.
- **SQLite FTS5** (available in the standard library's `sqlite3`, no new dependency) provides relevance-ranked text retrieval over titles, descriptions, and stored analyses.
- **Two-stage similarity:** FTS5 plus structured filters retrieve a wide candidate set; Gemini judges which candidates are *conceptually* similar during `analyze`. This is exactly the deterministic/LLM split the project requires — Python retrieves, the model judges.
- Because the corpus is small, the candidate set can be deliberately wide (~20), which compensates for keyword retrieval's lower recall versus semantic search.
- **Upgrade path if recall proves insufficient:** an `embedding BLOB` column on `problems` plus cosine similarity in numpy. Roughly a 30-line change against a schema that already has room for it. Deliberately deferred until the miss rate is observed rather than assumed.
- §12's `similarity` component reads *stored* similar-problem links established at analyze time; it does not recompute similarity at recommendation time.

### Database

- SQLite, tables: `users`, `problems`, `patterns`, `problem_patterns`, `attempts`, `recommendations`, `reviews`.
- **Schema additions beyond the original brief:**
  - `attempts.source` — distinguishes `leetcode` from `self_reported`.
  - `attempts.failure_type` — nullable, holding A–E or `unknown`.
  - `problems.pattern_source` — `tags` or `llm`.
  - `problems.is_paid_only` — so paid problems can be excluded from recommendations.
  - An **FTS5 shadow table** over problem text, kept in sync on write.
- Single local user; no authentication.

### Application services

- CLI, FastAPI routes, and the scheduler are all thin adapters over the same application services. **No business logic in route handlers or CLI commands.**
- `ask` starts life at Milestone 1 as a plain provider passthrough (proving config and provider wiring before tools exist) and is **upgraded in place** into a read-only agent once the registry and database exist.

### Milestone ordering

- **Milestones 3 and 4 from the original brief are swapped**: SQLite comes *before* problem analysis.
- Rationale: the original order has Milestone 3 "save analysis" with no database to save to, forcing a throwaway JSON layer that Milestone 4 immediately replaces. It also leaves `search_problems` with nothing to search, weakening the Milestone 2 demo.
- Revised order: setup → tool calling → **SQLite** → problem analysis → learning system → recommendation engine → review → scheduler → FastAPI → web UI.

### Milestone 1 scope

Python project scaffold, virtual environment instructions, dependencies, configuration loading, `.env.example`, `LLMProvider` interface, `GeminiProvider`, Pydantic schemas, and a basic CLI with `ask` as a plain passthrough.

Verification command: `python -m app.cli ask "Explain sliding window"`

## Testing Decisions

### What makes a good test here

Tests assert **external behavior**, not implementation details. A test should describe something a user or caller cares about — "a pattern with a 40% success rate outranks one at 90%", "an expired cookie does not wipe history", "asking a question never writes to the database" — and should survive a rewrite of the internals that satisfy it.

Tests must not assert on prompt text, on the number of internal function calls, or on the shape of intermediate data structures that no caller sees.

### Seams (confirmed with the developer)

**Three seams, with most value concentrated in the first two. The CLI and the live network boundary are deliberately not seams.**

**Seam 1 — `RecommendationEngine`.** The primary seam. A plain class taking learning history and candidates and returning a ranked list with score breakdowns. No LLM, no network, no CLI. This satisfies the hard requirement that the recommendation engine be testable without an API key.

Covers: pattern-weakness scoring, review-due detection, difficulty fit, time-since-practice, variety, weight configurability, **cold-start weight renormalization**, exclusion of recently-solved problems, inclusion of review-due problems, exclusion of `unknown` failure types from failure-driven scoring, and exclusion of paid-only problems.

**Seam 2 — `LLMProvider`.** The mocking seam. Every agent test injects a fake provider returning scripted tool calls and structured payloads, making the agent loop fully testable with no network and no key.

Covers: the loop terminates on a final answer; per-command iteration caps; read-only result caching within a turn; write-tools never cached; the repetition guard firing after N identical calls and producing an answer rather than raising; the guard *not* firing on varying arguments; `ask` being denied write tools; tool-argument validation rejecting malformed model output; tool errors returned to the model rather than raised.

**Seam 3 — the tool registry.** Tools are plain functions with Pydantic-validated arguments, directly callable in tests against an in-memory SQLite database. Because the API and CLI both route through the same services, testing tools covers both surfaces.

Covers: `search_problems` filtering and FTS5 ranking; `get_weak_patterns` computing correct success rates and last-practiced dates; `get_learning_history` aggregation; `record_attempt` and `save_problem_analysis` persistence; streak calculation; difficulty distribution.

### Explicitly not seams

- **The CLI.** Commands are thin wrappers over services; testing them would mostly re-test the services.
- **Live LeetCode and Gemini calls.** The network boundary is covered by contract-shaped fixtures captured from real responses. Real API calls are exercised only during manual milestone verification.

### Additional coverage

- **Sync safety** deserves a dedicated test: a `null` submission list must raise a clear auth error and leave the database untouched. This is the highest-consequence failure mode in the system — getting it wrong silently destroys real learning history.
- **Spaced-repetition scheduling**: successful reviews lengthen the interval, failed reviews shorten it, intervals are configurable.
- **Tag-to-pattern mapping**: the priority ordering resolves multi-tag problems to the expected primary pattern.

### Prior art

None — this is a greenfield project. These tests establish the conventions. `pytest` with fixtures for seeded in-memory SQLite databases and a `FakeLLMProvider` test double are the two building blocks everything else composes from.

## Out of Scope

- **Vector search and embeddings.** Deliberately deferred; the schema leaves room (`embedding BLOB`) for a later addition if keyword retrieval proves insufficient in practice.
- **Hosted databases of any kind**, including free-tier Postgres with pgvector. The project stays local-first.
- **LangChain, LangGraph, or any agent framework.** Migration may be reconsidered later, once the hand-written loop is understood.
- **Telegram, Discord, and email notifications.** The `NotificationService` interface is designed for them; only `ConsoleNotificationService` is implemented.
- **Ollama and OpenAI providers.** The `LLMProvider` abstraction must permit them; neither is built.
- **Docker.**
- **User authentication and multi-user support.** One local user.
- **Editorial solution ingestion.**
- **Automatic sync.** Sync is always an explicit, user-invoked command.
- **Elaborate UI design and animation.** The backend and agent are the point.
- **Final tuning of scoring weights and review intervals.** Both are configurable and are better tuned against real usage data than argued in advance.

## Further Notes

**Free-tier data usage.** Google's Gemini free tier uses submitted prompts for model training; the paid tier and Vertex AI do not. In this project that means problem text, generated analyses, and — via sync — practice history are sent under those terms. This is a direct and accepted consequence of the zero-cost constraint, on public problems and personal practice data. Recorded here so the trade-off is a choice rather than a discovery.

**Rate limits shape the architecture.** Free-tier Pro-tier quota (~50–100 requests/day) is small enough that an agentic command consuming 4–8 requests per run would exhaust it in roughly a dozen commands. This is the direct cause of the per-role model split, the per-turn tool cache, and the per-command iteration caps — they are cost controls as much as correctness controls.

**Verified during design, not assumed.** The LeetCode catalogue query (4,028 problems with tags and difficulty), the unauthenticated problem-detail query, the `null`-on-unauthenticated behavior of `submissionList`, and the unauthenticated availability of `recentAcSubmissionList` were all confirmed against the live endpoint before this spec was written.

**Deviations from the original brief**, all deliberate and agreed: milestones 3 and 4 swapped; `attempt` no longer asks "did you solve it?" when sync already knows; schema gains `attempts.source`, `attempts.failure_type`, `problems.pattern_source`, `problems.is_paid_only`, and an FTS5 shadow table; configuration gains a second model environment variable; `ask` is promoted from a throwaway smoke test to a permanent read-only agent surface.

**Development process.** Build proceeds one milestone at a time. After each: explain what was built, show the architecture, run the tests, fix failures, give manual verification steps, and stop for approval before continuing.
