"""Unit tests for the design-token resolver (ui.theme) — pure logic, no Qt."""

import os
import re

import pytest

from ui.theme import tokens
from ui.theme.qss import load_app_qss, qss, resolve, strip_comments

pytestmark = pytest.mark.unit

_VAR_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)")


def test_raw_token_returns_literal():
    assert resolve("--brand-cyan") == "#29abe2"
    assert resolve("--text-base") == "17px"
    assert resolve("--radius-lg") == "12px"


def test_semantic_aliases_resolve_through_var_chain():
    # --color-primary -> var(--blue-500) -> #3498db
    assert resolve("--color-primary") == "#3498db"
    assert resolve("--surface-page") == "#f8f9fa"
    assert resolve("--surface-dark") == "#1e1e1e"
    # two hops: --border-focus -> --color-primary -> --blue-500
    assert resolve("--border-focus") == "#3498db"


def test_resolve_inline_var_inside_string():
    assert resolve("2px solid var(--gray-400)") == "2px solid #bdc3c7"
    assert qss("padding: var(--space-3) var(--space-5);") == "padding: 12px 20px;"


def test_unknown_token_is_left_intact():
    # Graceful: an unknown reference is preserved verbatim, not blanked.
    assert resolve("var(--does-not-exist)") == "var(--does-not-exist)"


def test_every_internal_var_reference_targets_a_real_token():
    """No token value may reference a --name that isn't defined."""
    for name, value in tokens.TOKENS.items():
        for ref in _VAR_RE.findall(value):
            assert ref in tokens.TOKENS, f"{name} references undefined token {ref}"


def test_app_qss_only_uses_defined_tokens():
    """Every var(--x) in app.qss rules must resolve (guards against typos).

    Comments are stripped first so documentation prose mentioning var() examples
    is not mistaken for a real reference.
    """
    app_qss_path = os.path.join(os.path.dirname(tokens.__file__), "app.qss")
    with open(app_qss_path, encoding="utf-8") as fh:
        rules = strip_comments(fh.read())
    for ref in set(_VAR_RE.findall(rules)):
        assert ref in tokens.TOKENS, f"app.qss references undefined token {ref}"


def test_rendered_app_qss_has_no_unresolved_vars():
    rendered = load_app_qss()
    assert "var(" not in rendered, "app.qss still contains unresolved var() refs"
    # sanity: the primary interactive blue made it into the stylesheet
    assert "#3498db" in rendered
