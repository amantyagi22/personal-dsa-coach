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
structure (String, priority 900). That classifies the whole 4,028-problem
catalogue instantly with no LLM cost. Gemini's judgement during `analyze`
overrides it per problem and is authoritative from then on.
"""

from __future__ import annotations

from typing import NamedTuple


class SeedPattern(NamedTuple):
    name: str
    slug: str
    priority: int
    leetcode_tag: str | None
    description: str


# Priority bands:
#   10-99    distinctive techniques - if the tag is present, it is the point
#   100-499  named algorithm families
#   500-899  broad approaches
#   900+     data structures, which describe what a problem uses rather than
#            what it tests, and so are the fallback of last resort
CANONICAL_PATTERNS: list[SeedPattern] = [
    SeedPattern(
        "Sliding Window",
        "sliding-window",
        10,
        "Sliding Window",
        "A window over a contiguous range that grows and shrinks as it scans.",
    ),
    SeedPattern(
        "Two Pointers",
        "two-pointers",
        20,
        "Two Pointers",
        "Two indices moving through a sequence, often from both ends.",
    ),
    SeedPattern(
        "Monotonic Stack",
        "monotonic-stack",
        30,
        "Monotonic Stack",
        "A stack kept sorted, for next-greater and previous-smaller questions.",
    ),
    SeedPattern(
        "Binary Search",
        "binary-search",
        40,
        "Binary Search",
        "Halving a sorted space, or searching over an answer range.",
    ),
    SeedPattern(
        "Prefix Sum",
        "prefix-sum",
        50,
        "Prefix Sum",
        "Precomputed running totals that make range queries constant time.",
    ),
    SeedPattern(
        "Backtracking",
        "backtracking",
        60,
        "Backtracking",
        "Exhaustive search that undoes each choice before trying the next.",
    ),
    SeedPattern(
        "Union Find",
        "union-find",
        70,
        "Union Find",
        "Disjoint sets with near-constant merging, for connectivity questions.",
    ),
    SeedPattern(
        "Trie",
        "trie",
        80,
        "Trie",
        "A prefix tree, for questions about shared string prefixes.",
    ),
    SeedPattern(
        "Topological Sort",
        "topological-sort",
        90,
        "Topological Sort",
        "Ordering a directed acyclic graph by dependency.",
    ),
    SeedPattern(
        "Dynamic Programming",
        "dynamic-programming",
        100,
        "Dynamic Programming",
        "Overlapping subproblems solved once and reused.",
    ),
    SeedPattern(
        "Greedy",
        "greedy",
        110,
        "Greedy",
        "Taking the locally best choice when it provably gives the global best.",
    ),
    SeedPattern(
        "Divide and Conquer",
        "divide-and-conquer",
        120,
        "Divide and Conquer",
        "Splitting a problem into independent parts and combining the results.",
    ),
    SeedPattern(
        "Depth-First Search",
        "depth-first-search",
        130,
        "Depth-First Search",
        "Exploring as far as possible along each branch before backtracking.",
    ),
    SeedPattern(
        "Breadth-First Search",
        "breadth-first-search",
        140,
        "Breadth-First Search",
        "Level-by-level exploration, which finds shortest paths in unweighted graphs.",
    ),
    SeedPattern(
        "Shortest Path",
        "shortest-path",
        150,
        "Shortest Path",
        "Dijkstra, Bellman-Ford, and friends, for weighted graphs.",
    ),
    SeedPattern(
        "Bit Manipulation",
        "bit-manipulation",
        160,
        "Bit Manipulation",
        "Solving with the binary representation itself.",
    ),
    SeedPattern(
        "Math",
        "math",
        170,
        "Math",
        "Number theory, combinatorics, and arithmetic insight.",
    ),
    SeedPattern(
        "Sorting",
        "sorting",
        200,
        "Sorting",
        "Problems where arranging the data in order is the key step.",
    ),
    SeedPattern(
        "Recursion",
        "recursion",
        210,
        "Recursion",
        "Self-referential decomposition without memoisation.",
    ),
    SeedPattern(
        "Simulation",
        "simulation",
        500,
        "Simulation",
        "Following the stated rules directly, with no clever insight required.",
    ),
    SeedPattern(
        "Design",
        "design",
        510,
        "Design",
        "Building a data structure to meet a stated interface and complexity.",
    ),
    SeedPattern(
        "Heap",
        "heap",
        900,
        "Heap (Priority Queue)",
        "A priority queue, for repeatedly taking the largest or smallest.",
    ),
    SeedPattern(
        "Graph",
        "graph",
        910,
        "Graph",
        "Problems framed on nodes and edges.",
    ),
    SeedPattern(
        "Tree",
        "tree",
        920,
        "Tree",
        "Binary trees, n-ary trees, and their traversals.",
    ),
    SeedPattern(
        "Linked List",
        "linked-list",
        930,
        "Linked List",
        "Pointer manipulation over a chain of nodes.",
    ),
    SeedPattern(
        "Hash Table",
        "hash-table",
        940,
        "Hash Table",
        "Constant-time lookup by key.",
    ),
    SeedPattern(
        "Stack",
        "stack",
        950,
        "Stack",
        "Last-in-first-out access.",
    ),
    SeedPattern(
        "Queue",
        "queue",
        960,
        "Queue",
        "First-in-first-out access.",
    ),
    SeedPattern(
        "String",
        "string",
        970,
        "String",
        "Problems whose substance is text manipulation.",
    ),
    SeedPattern(
        "Array",
        "array",
        980,
        "Array",
        "The fallback: a problem over a plain sequence with no stronger signal.",
    ),
    SeedPattern(
        "Matrix",
        "matrix",
        985,
        "Matrix",
        "Two-dimensional grids.",
    ),
    SeedPattern(
        "Other",
        "other",
        9999,
        None,
        "No canonical pattern applies, or the tags gave nothing to go on.",
    ),
]
