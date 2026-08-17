"""The canonical DSA pattern taxonomy.

Seeded into the patterns table rather than hard-coded as an enum, so the
vocabulary can be edited in the database without a code change. This module is
the initial content, not the runtime source of truth - everything reads the
table.

**Priority is the interesting part.** LeetCode's topic tags are an unordered bag:
"Two Sum" is tagged Array, Hash Table; "Longest Substring Without Repeating
Characters" is tagged Hash Table, String, Sliding Window. Neither says which tag
is the point of the problem.

The mapping resolves that deterministically: the lowest priority number wins, so
a specific technique (Sliding Window, priority 10) beats a generic data
structure (String, priority 970). That classifies the whole catalogue instantly
with no LLM cost. Gemini's judgement during `analyze` overrides it per problem
and is authoritative from then on.

**The tags were surveyed, not guessed.** The live catalogue uses 175 distinct
tags across 4,028 problems. Several name the same idea to a learner - "Graph
Theory", "Graph", and "Bipartite Graph" are all graph problems - so each pattern
carries a list. Tags are matched exactly as LeetCode spells them, including the
hyphen in "Union-Find" and the parenthetical in "Heap (Priority Queue)".
"""

from __future__ import annotations

from typing import NamedTuple


class SeedPattern(NamedTuple):
    name: str
    slug: str
    priority: int
    leetcode_tags: tuple[str, ...]
    description: str


# Priority bands:
#   10-99    distinctive techniques - if the tag is present, it is the point
#   100-499  named algorithm families
#   500-899  broad approaches
#   900+     data structures, which describe what a problem uses rather than
#            what it tests, and so are the fallback of last resort
#   9000+    non-DSA and unclassifiable
CANONICAL_PATTERNS: list[SeedPattern] = [
    SeedPattern(
        "Sliding Window",
        "sliding-window",
        10,
        ("Sliding Window",),
        "A window over a contiguous range that grows and shrinks as it scans.",
    ),
    SeedPattern(
        "Two Pointers",
        "two-pointers",
        20,
        ("Two Pointers",),
        "Two indices moving through a sequence, often from both ends.",
    ),
    SeedPattern(
        "Monotonic Stack",
        "monotonic-stack",
        30,
        ("Monotonic Stack", "Monotonic Queue"),
        "A stack kept sorted, for next-greater and previous-smaller questions.",
    ),
    SeedPattern(
        "Binary Search",
        "binary-search",
        40,
        ("Binary Search",),
        "Halving a sorted space, or searching over an answer range.",
    ),
    SeedPattern(
        "Prefix Sum",
        "prefix-sum",
        50,
        ("Prefix Sum",),
        "Precomputed running totals that make range queries constant time.",
    ),
    SeedPattern(
        "Backtracking",
        "backtracking",
        60,
        ("Backtracking",),
        "Exhaustive search that undoes each choice before trying the next.",
    ),
    SeedPattern(
        "Union Find",
        "union-find",
        70,
        ("Union-Find",),
        "Disjoint sets with near-constant merging, for connectivity questions.",
    ),
    SeedPattern(
        "Trie",
        "trie",
        80,
        ("Trie",),
        "A prefix tree, for questions about shared string prefixes.",
    ),
    SeedPattern(
        "Topological Sort",
        "topological-sort",
        90,
        ("Topological Sort", "Directed Acyclic Graph"),
        "Ordering a directed acyclic graph by dependency.",
    ),
    SeedPattern(
        "Dynamic Programming",
        "dynamic-programming",
        100,
        (
            "Dynamic Programming",
            "Memoization",
            "DP on Trees",
            "Knapsack Problem",
            "Longest Increasing Subsequence",
            "Bitmask",
        ),
        "Overlapping subproblems solved once and reused.",
    ),
    SeedPattern(
        "Greedy",
        "greedy",
        110,
        ("Greedy",),
        "Taking the locally best choice when it provably gives the global best.",
    ),
    SeedPattern(
        "Divide and Conquer",
        "divide-and-conquer",
        120,
        ("Divide and Conquer", "Merge Sort", "Quickselect", "Binary Lifting"),
        "Splitting a problem into independent parts and combining the results.",
    ),
    SeedPattern(
        "Depth-First Search",
        "depth-first-search",
        130,
        ("Depth-First Search",),
        "Exploring as far as possible along each branch before backtracking.",
    ),
    SeedPattern(
        "Breadth-First Search",
        "breadth-first-search",
        140,
        ("Breadth-First Search",),
        "Level-by-level exploration, which finds shortest paths in unweighted graphs.",
    ),
    SeedPattern(
        "Shortest Path",
        "shortest-path",
        150,
        ("Shortest Path", "Dijkstra's Algorithm"),
        "Dijkstra, Bellman-Ford, and friends, for weighted graphs.",
    ),
    SeedPattern(
        "Bit Manipulation",
        "bit-manipulation",
        160,
        ("Bit Manipulation",),
        "Solving with the binary representation itself.",
    ),
    SeedPattern(
        "String Matching",
        "string-matching",
        170,
        (
            "String Matching",
            "Rolling Hash",
            "Z Algorithm",
            "Knuth-Morris-Pratt Algorithm",
            "Knuth–Morris–Pratt Algorithm",
            "Suffix Array",
            "Hash Function",
        ),
        "Finding patterns inside text faster than the naive scan.",
    ),
    SeedPattern(
        "Math",
        "math",
        180,
        (
            "Math",
            "Number Theory",
            "Combinatorics",
            "Geometry",
            "Prime Factorization",
            "Sieve Theory",
            "Primality Test",
            "Greatest Common Divisor",
            "Euclidean Algorithm",
            "Fermat's Little Theorem",
            "Probability and Statistics",
        ),
        "Number theory, combinatorics, and arithmetic insight.",
    ),
    SeedPattern(
        "Game Theory",
        "game-theory",
        190,
        ("Game Theory", "Minimax", "Zero-Sum Game"),
        "Reasoning about an adversary who also plays optimally.",
    ),
    SeedPattern(
        "Sorting",
        "sorting",
        200,
        ("Sorting", "Counting Sort", "Bucket Sort", "Radix Sort"),
        "Problems where arranging the data in order is the key step.",
    ),
    SeedPattern(
        "Recursion",
        "recursion",
        210,
        ("Recursion",),
        "Self-referential decomposition without memoisation.",
    ),
    SeedPattern(
        "Segment Tree",
        "segment-tree",
        220,
        ("Segment Tree", "Binary Indexed Tree", "Line Sweep", "Sweep Line"),
        "Range queries and updates over an interval structure.",
    ),
    SeedPattern(
        "Counting",
        "counting",
        400,
        ("Counting", "Enumeration"),
        "Tallying occurrences, usually with a frequency map.",
    ),
    SeedPattern(
        "Simulation",
        "simulation",
        500,
        ("Simulation", "Brainteaser", "Interactive", "Randomized"),
        "Following the stated rules directly, with no clever insight required.",
    ),
    SeedPattern(
        "Design",
        "design",
        510,
        ("Design", "Data Stream", "Iterator", "Concurrency"),
        "Building a data structure to meet a stated interface and complexity.",
    ),
    SeedPattern(
        "Heap",
        "heap",
        900,
        ("Heap (Priority Queue)",),
        "A priority queue, for repeatedly taking the largest or smallest.",
    ),
    SeedPattern(
        "Graph",
        "graph",
        910,
        ("Graph", "Graph Theory", "Bipartite Graph", "Strongly Connected Component"),
        "Problems framed on nodes and edges.",
    ),
    SeedPattern(
        "Tree",
        "tree",
        920,
        (
            "Tree",
            "Binary Tree",
            "Binary Search Tree",
            "N-ary Tree",
            "Lowest Common Ancestor",
            "Trie Tree",
        ),
        "Binary trees, n-ary trees, and their traversals.",
    ),
    SeedPattern(
        "Linked List",
        "linked-list",
        930,
        ("Linked List", "Doubly-Linked List"),
        "Pointer manipulation over a chain of nodes.",
    ),
    SeedPattern(
        "Hash Table",
        "hash-table",
        940,
        ("Hash Table",),
        "Constant-time lookup by key.",
    ),
    SeedPattern(
        "Stack",
        "stack",
        950,
        ("Stack", "Bracket Sequences"),
        "Last-in-first-out access.",
    ),
    SeedPattern(
        "Queue",
        "queue",
        960,
        ("Queue",),
        "First-in-first-out access.",
    ),
    SeedPattern(
        "Ordered Set",
        "ordered-set",
        965,
        ("Ordered Set",),
        "A sorted collection with fast insertion and rank queries.",
    ),
    SeedPattern(
        "String",
        "string",
        970,
        ("String",),
        "Problems whose substance is text manipulation.",
    ),
    SeedPattern(
        "Matrix",
        "matrix",
        980,
        ("Matrix",),
        "Two-dimensional grids.",
    ),
    SeedPattern(
        "Array",
        "array",
        985,
        ("Array",),
        "The fallback: a problem over a plain sequence with no stronger signal.",
    ),
    # Non-DSA. SQL and shell problems are in the same catalogue but are not what
    # this coach teaches, so they get their own pattern and can be filtered out
    # rather than polluting Array with 300 database questions.
    SeedPattern(
        "Database",
        "database",
        9000,
        ("Database",),
        "SQL problems. Not a DSA pattern - excluded from recommendations.",
    ),
    SeedPattern(
        "Shell",
        "shell",
        9010,
        ("Shell",),
        "Shell scripting problems. Not a DSA pattern.",
    ),
    SeedPattern(
        "Other",
        "other",
        9999,
        (),
        "No canonical pattern applies, or the problem carries no tags at all.",
    ),
]
