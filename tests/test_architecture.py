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
