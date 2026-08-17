"""Architectural rules enforced as tests.

These exist because the rules are invisible at review time - nothing about
importing google.genai in a service module looks wrong until you try to swap
providers and find the SDK threaded through twenty files.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
PROVIDER_PACKAGE = APP / "llm"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_only_the_provider_package_imports_the_gemini_sdk():
    offenders = [
        path.relative_to(APP.parent)
        for path in APP.rglob("*.py")
        if PROVIDER_PACKAGE not in path.parents
        and any(name.startswith("google") for name in imported_modules(path))
    ]

    assert offenders == [], (
        f"These modules import the Gemini SDK directly: {offenders}. "
        f"Only app/llm may - everything else depends on LLMProvider."
    )


def test_the_provider_interface_itself_is_vendor_free():
    """base.py is what other packages import; it must stay swappable."""
    names = imported_modules(PROVIDER_PACKAGE / "base.py")

    assert not any(name.startswith("google") for name in names)


def test_network_access_is_confined_to_its_own_packages():
    """Tests must run with no network. A stray urllib import in a service module
    is how that stops being true - and it fails only on a plane, not in CI.
    """
    allowed = {APP / "problems", APP / "llm"}
    offenders = [
        path.relative_to(APP.parent)
        for path in APP.rglob("*.py")
        if not any(parent in allowed for parent in path.parents)
        and any(
            name.startswith(("urllib", "http", "requests", "socket"))
            for name in imported_modules(path)
        )
    ]

    assert offenders == [], (
        f"These modules reach the network directly: {offenders}. "
        f"Network access belongs in app/problems (LeetCode) or app/llm (Gemini)."
    )


def test_the_agent_loop_does_not_depend_on_any_specific_tool():
    """The loop is generic machinery. If it knows about LeetCode, it is no longer
    a loop - it is one command with extra steps.
    """
    names = imported_modules(APP / "agent" / "loop.py")

    assert not any("problems" in name or "leetcode" in name for name in names)


def test_only_config_reads_the_environment():
    offenders = [
        path.relative_to(APP.parent)
        for path in APP.rglob("*.py")
        if path.name != "config.py" and "os.environ" in path.read_text()
    ]

    assert offenders == [], (
        f"These modules read the environment directly: {offenders}. "
        f"Configuration is loaded once in app/config.py."
    )
