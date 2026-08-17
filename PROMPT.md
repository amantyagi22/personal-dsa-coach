# Build: Personal DSA Coach AI Agent

You are the lead AI/backend engineer building a local-first **Personal DSA Coach AI Agent** for me.

I am a backend engineer and I am specifically building this project to learn how AI agents work in practice.

The goal is NOT to build a generic chatbot.

The goal is to build an agent that understands my DSA history, analyzes LeetCode problems, identifies patterns, tracks my weaknesses, and recommends the most suitable problem for me every day.

---

# 1. Core Product

Build an application where I can:

### Analyze a LeetCode problem

I provide:

```bash
python -m app.cli analyze <leetcode-url>
```

The agent should:

1. Fetch the problem.
2. Understand the problem.
3. Identify the primary DSA pattern.
4. Identify secondary techniques.
5. Explain why that pattern applies.
6. Explain the algorithm.
7. Explain complexity.
8. Explain how to recognize the pattern in future problems.
9. Identify common mistakes.
10. Search my previously analyzed problems for similar problems.
11. Save the analysis to my knowledge base.

---

# 2. Main Agent Feature

The most important feature is:

```bash
python -m app.cli today
```

The agent should answer:

> "Which ONE problem should I solve today?"

It must NOT randomly select a problem.

It should consider:

- weak DSA patterns
- previous attempts
- failed attempts
- pattern mastery
- time since last practice
- difficulty
- recent problems
- review schedule
- variety
- whether I repeatedly make the same mistake

Example:

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

Do not look at the solution for the first 30 minutes.
```

The recommendation must be explainable.

---

# 3. Important Architectural Principle

Do NOT make everything an LLM decision.

Separate:

### Deterministic application logic

Python should calculate:

- success rates
- weak patterns
- review dates
- recommendation scores
- difficulty progression
- attempt statistics
- streaks
- time since practice

### LLM reasoning

The LLM should handle:

- problem understanding
- pattern identification
- algorithm explanation
- recognizing conceptual similarities
- explaining recommendation rationale
- evaluating natural-language reasoning

The LLM should NOT directly calculate user statistics when Python can do it reliably.

---

# 4. Technology

Use:

```text
Python 3.12+
Gemini API
Pydantic
SQLite
SQLAlchemy
FastAPI
pytest
APScheduler
```

Use Gemini as the initial model provider.

I already have a Gemini API key.

The project must cost **₹0 during development**.

Do not introduce paid services.

Do not require OpenAI.

Do not require a paid database.

Do not require a paid vector database.

Do not require Docker initially.

---

# 5. Do NOT use LangChain initially

This is extremely important.

I am building this project to understand agents.

Implement the basic agent/tool-calling loop yourself.

I want to understand:

```text
User
 ↓
LLM
 ↓
Tool call
 ↓
Python function
 ↓
Tool result
 ↓
LLM
 ↓
Tool call
 ↓
...
 ↓
Final response
```

Do not hide this behind:

```python
create_agent(...)
```

or similar abstractions.

Later, the architecture can be migrated to LangGraph if there is a real reason.

---

# 6. LLM abstraction

Create an abstraction:

```python
class LLMProvider:
    ...
```

Implement:

```python
GeminiProvider
```

The rest of the application must not depend directly on Gemini.

Eventually I should be able to add:

```text
GeminiProvider
OllamaProvider
OpenAIProvider
```

without rewriting the agent.

Configuration:

```env
GEMINI_API_KEY=
GEMINI_MODEL=
```

Create:

```text
.env.example
```

Never commit `.env`.

---

# 7. Agent Tools

Create explicit Python tools.

Initial tools:

## get_leetcode_problem

```python
get_leetcode_problem(url: str)
```

Returns:

```json
{
  "title": "...",
  "url": "...",
  "difficulty": "...",
  "description": "...",
  "examples": [],
  "constraints": [],
  "tags": []
}
```

Use a reliable public source.

Do not hard-code problems.

---

## search_problems

Search my local problem database.

Inputs:

```python
query: str | None
pattern: str | None
difficulty: str | None
limit: int
```

Return similar previously analyzed problems.

---

## save_problem_analysis

Save:

```text
title
url
difficulty
description
primary_pattern
secondary_patterns
algorithm
intuition
complexity
recognition_clues
common_mistakes
similar_problems
date_analyzed
```

---

## get_learning_history

Return:

```text
recent problems
attempts
success rates
pattern statistics
last practice dates
difficulty statistics
```

---

## get_weak_patterns

Return deterministic pattern statistics.

Example:

```text
Sliding Window
Attempts: 8
Successful: 4
Success Rate: 50%
Last Practiced: 6 days ago
```

---

## record_attempt

Store:

```python
problem_id
solved
time_minutes
pattern_identified
used_hint
notes
```

---

## save_recommendation

Store:

```text
problem
date
pattern
difficulty
score
reason
```

---

# 8. Agent Tool Calling

The agent should work approximately like this:

```text
User:
Analyze this LeetCode problem.

        ↓

LLM decides:
I need problem information.

        ↓

get_leetcode_problem()

        ↓

Python returns problem

        ↓

LLM reasons about:
- pattern
- algorithm
- complexity
- recognition clues

        ↓

search_problems()

        ↓

Python returns similar problems

        ↓

LLM produces final analysis

        ↓

save_problem_analysis()

        ↓

Final response
```

Implement:

- tool registry
- tool schemas
- tool execution
- argument validation
- tool errors
- maximum iteration limit
- logging

Prevent infinite tool loops.

---

# 9. Problem Analysis Output

The agent should produce:

```text
Problem
Pattern
Secondary Techniques

Why this pattern?

Key Observation

Algorithm

Step-by-step reasoning

Complexity

How to recognize this pattern

Common mistakes

Similar problems
```

The most important section is:

## How to recognize this pattern

For example:

```text
Look for:

• contiguous substring/subarray
• longest/shortest
• duplicate/frequency constraints
• two boundaries
• a condition that can be maintained while expanding/shrinking
```

The goal is to improve pattern recognition, not merely explain the solution.

---

# 10. Learning Model

Track pattern mastery.

Example:

```text
Pattern              Attempts   Success   Mastery

Two Pointers              8        7       87%
Sliding Window            6        3       50%
Binary Search             7        6       85%
DFS                       9        8       89%
Dynamic Programming       5        2       40%
```

Do this with deterministic Python logic.

Do not ask Gemini to calculate these values.

---

# 11. Distinguish Different Failure Types

This is important.

Track whether:

```text
A. Could not identify the pattern

B. Identified pattern but could not derive algorithm

C. Derived algorithm but implementation failed

D. Correct solution but too slow

E. Correct solution
```

The recommendation system should use this information.

Example:

If I repeatedly identify Sliding Window correctly but fail implementation:

```text
Recommend implementation-focused Sliding Window problems.
```

If I repeatedly fail to identify Sliding Window:

```text
Recommend simpler pattern-recognition problems.
```

---

# 12. Recommendation Engine

Create:

```python
RecommendationEngine
```

It should first generate candidate problems using deterministic logic.

Then score them.

Initial scoring:

```text
pattern_weakness        30%
review_due              25%
difficulty_fit          20%
time_since_practice     10%
similarity               10%
variety                   5%
```

Make the weights configurable.

Do NOT call Gemini for every candidate.

Python should rank candidates.

Gemini can explain the final choice.

---

# 13. Spaced Review

Implement basic spaced repetition.

For example:

```text
successful:
1 day
3 days
7 days
14 days
30 days

failed:
review sooner
```

Make this configurable.

Do not over-engineer it into a full ML system.

---

# 14. Daily Recommendation

Implement:

```bash
python -m app.cli today
```

Flow:

```text
Load learning history
        ↓
Calculate weak patterns
        ↓
Find review-due problems
        ↓
Generate candidate problems
        ↓
Score candidates
        ↓
Select ONE problem
        ↓
Gemini explains why
        ↓
Save recommendation
        ↓
Display recommendation
```

Do not recommend a problem already solved recently unless it is intentionally due for review.

---

# 15. Review Mode

Implement:

```bash
python -m app.cli review
```

The agent should give me a previously studied problem WITHOUT immediately revealing the solution.

Ask me:

```text
1. What pattern is this?
2. Why?
3. What algorithm would you use?
4. What is the complexity?
```

Then evaluate my answer.

Record the evaluation.

---

# 16. Attempt Mode

Implement:

```bash
python -m app.cli attempt <problem-id>
```

Ask:

```text
Did you solve it?
How long did it take?
Did you identify the pattern?
Did you use a hint?
What went wrong?
```

Store the result.

---

# 17. Stats

Implement:

```bash
python -m app.cli stats
```

Display:

```text
Problems Solved
Problems Attempted
Current Streak
Average Solve Time

Strongest Patterns

Weakest Patterns

Patterns Due for Review

Difficulty Distribution
```

---

# 18. Database

Use SQLite.

Tables:

```text
users
problems
patterns
problem_patterns
attempts
recommendations
reviews
```

Do not create a user authentication system.

There is only one local user.

Keep the schema simple.

---

# 19. Web API

After the CLI and agent work, add FastAPI.

Endpoints:

```text
POST /analyze
GET  /today
GET  /problems
GET  /problems/{id}
POST /attempts
GET  /stats
GET  /patterns
GET  /reviews
```

The API must use the same application services as the CLI.

Do NOT duplicate business logic inside route handlers.

Architecture:

```text
CLI ───────┐
           │
Web API ───┼──→ Application Services
           │
Scheduler ┘
                 ↓
              Agent
                 ↓
              Tools
                 ↓
             Database
```

---

# 20. Web UI

Build a minimal web dashboard only AFTER the backend works.

Use a simple frontend.

The UI should have:

## Dashboard

Show:

```text
Today's Problem
Weak Patterns
Recent Activity
Current Streak
```

## Today's Problem

Show:

```text
Problem
Difficulty
Pattern
Why it was selected
Start button
```

## Problem Library

Search/filter by:

```text
pattern
difficulty
status
```

## Problem Analysis

Show:

```text
Pattern
Algorithm
Complexity
Recognition clues
Common mistakes
Similar problems
```

## Progress

Show pattern mastery.

Keep the UI simple.

Do not spend excessive time on animations/design.

The backend/agent is the important part.

---

# 21. Morning Scheduler

Use APScheduler.

Default:

```text
08:00 local time
```

Every morning:

```text
load history
→ calculate recommendation
→ generate explanation
→ save recommendation
→ send notification
```

Initially implement:

```python
ConsoleNotificationService
```

Create an interface so later we can add:

```text
TelegramNotificationService
DiscordNotificationService
EmailNotificationService
```

Do not implement those yet.

---

# 22. Project Structure

Use something close to:

```text
dsa-coach/
│
├── app/
│   ├── agent/
│   │   ├── agent.py
│   │   ├── tools.py
│   │   ├── prompts.py
│   │   └── schemas.py
│   │
│   ├── llm/
│   │   ├── base.py
│   │   └── gemini.py
│   │
│   ├── problems/
│   │   ├── scraper.py
│   │   └── service.py
│   │
│   ├── learning/
│   │   ├── mastery.py
│   │   ├── recommender.py
│   │   └── review.py
│   │
│   ├── storage/
│   │   ├── database.py
│   │   ├── models.py
│   │   └── repository.py
│   │
│   ├── api/
│   │   └── routes.py
│   │
│   ├── scheduler/
│   │   └── jobs.py
│   │
│   └── cli.py
│
├── frontend/
│
├── tests/
│
├── data/
│
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

---

# 23. Development Rules

Do NOT generate the entire project in one response.

Build it milestone by milestone.

After each milestone:

1. Explain what was built.
2. Show the architecture.
3. Run tests.
4. Fix failures.
5. Tell me how to manually test it.
6. Wait for my approval before moving to the next milestone.

Do not pretend something works without testing it.

Use type hints.

Use Pydantic models for structured LLM data.

Use proper exception handling.

Add logging.

Keep functions small.

Avoid unnecessary abstractions.

Avoid premature optimization.

---

# 24. Milestones

## Milestone 1 — Project Setup

Build:

- Python project
- virtual environment instructions
- dependencies
- configuration
- Gemini provider
- Pydantic schemas
- basic CLI

Test:

```bash
python -m app.cli ask "Explain sliding window"
```

---

## Milestone 2 — Tool Calling

Build:

- tool registry
- tool schemas
- manual agent loop
- tool execution
- get_leetcode_problem

Demonstrate that Gemini can request a Python tool.

---

## Milestone 3 — Problem Analysis

Build:

- structured analysis
- pattern identification
- algorithm explanation
- recognition clues
- save analysis

---

## Milestone 4 — SQLite

Build:

- database
- models
- repositories
- problem history

---

## Milestone 5 — Learning System

Build:

- attempts
- pattern mastery
- weak pattern calculation
- review scheduling

---

## Milestone 6 — Recommendation Engine

Build:

```bash
python -m app.cli today
```

with deterministic scoring.

---

## Milestone 7 — Review System

Build:

```bash
python -m app.cli review
```

and evaluation.

---

## Milestone 8 — Scheduler

Build:

```text
08:00 daily recommendation
```

using APScheduler.

---

## Milestone 9 — FastAPI

Expose the application through REST endpoints.

---

## Milestone 10 — Web UI

Build the minimal dashboard.

---

# 25. Testing Requirements

Write unit tests for:

```text
recommendation scoring
pattern mastery
weak pattern detection
review scheduling
difficulty selection
repository operations
tool validation
```

Mock the LLM in unit tests.

The recommendation engine must be testable without an API key.

---

# 26. README

Create a README explaining:

```text
What this project does

Architecture

How the agent works

Tool calling

LLM reasoning vs deterministic logic

Recommendation engine

Learning model

Database schema

How to run locally

How to configure Gemini

How to run tests

Future Ollama/local-model support
```

Include a sequence diagram:

```text
User
 ↓
Agent
 ↓
LLM
 ↓
Tool
 ↓
Python
 ↓
Database/API
 ↓
Tool Result
 ↓
LLM
 ↓
Final Response
```

---

# 27. Future Local Model Support

Do not implement this initially.

But ensure the architecture allows:

```text
                    Agent Core
                        │
                   LLMProvider
                  /            \
                 /              \
             Gemini            Ollama
              API              Local
```

Eventually I want to be able to run the same agent with an open-source local model.

---

# 28. Critical Requirement

The project should demonstrate genuine agent behavior.

Do NOT build:

```text
User → prompt → Gemini → response
```

and call that an agent.

I want:

```text
User
 ↓
Agent
 ↓
LLM decides what information it needs
 ↓
Tool call
 ↓
Python executes tool
 ↓
Result
 ↓
LLM decides next action
 ↓
More tools if necessary
 ↓
Final result
```

The agent should be able to decide which tools it needs instead of following a completely hard-coded sequence.

At the same time, deterministic recommendation/business logic should remain outside the LLM.

---

# 29. First Task

Start with **Milestone 1 only**.

Before writing code:

1. Inspect the current directory.
2. Check whether a project already exists.
3. Do not overwrite unrelated files.
4. Propose the exact architecture briefly.
5. Then implement Milestone 1.
6. Run the tests.
7. Give me the commands required to run it.

Do NOT continue to Milestone 2 until I explicitly tell you to continue.
