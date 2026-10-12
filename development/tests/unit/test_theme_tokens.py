"""Unit tests for the design-token resolver (ui.theme) — pure logic, no Qt."""

import os
import re

import pytest

from ui.theme import tokens
from ui.theme.qss import (
    _UNKNOWN_TOKEN_FALLBACK,
    _warned_tokens,
    load_app_qss,
    qss,
    resolve,
    strip_comments,
)

pytestmark = pytest.mark.unit

_VAR_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)")


def test_raw_token_returns_literal():
    assert resolve("--brand-cyan") == "#29abe2"
    assert resolve("--text-base") == "18px"
    assert resolve("--radius-lg") == "12px"


def test_semantic_aliases_resolve_through_var_chain():
    # --color-primary -> var(--blue-500) -> #176b9a
    assert resolve("--color-primary") == "#176b9a"
    assert resolve("--surface-page") == "#edf3f7"
    assert resolve("--surface-dark") == "#172f42"
    # two hops: --border-focus -> --color-primary -> --blue-500
    assert resolve("--border-focus") == "#176b9a"


def test_resolve_inline_var_inside_string():
    assert resolve("2px solid var(--gray-400)") == "2px solid #bdc3c7"
    assert qss("padding: var(--space-3) var(--space-5);") == "padding: 12px 20px;"


def test_unknown_token_falls_back_to_safe_literal(caplog):
    """An unknown reference resolves to the safe fallback (valid QSS), not
    the raw var(...) text (invalid QSS that could poison the rule), and it
    warns so the typo is visible in the logs."""
    import logging as _logging

    _warned_tokens.discard("--does-not-exist")
    with caplog.at_level(_logging.WARNING, logger="kneespa.theme"):
        result = resolve("var(--does-not-exist)")

    assert result == _UNKNOWN_TOKEN_FALLBACK
    assert "var(" not in result
    assert any("--does-not-exist" in r.getMessage() for r in caplog.records)


def test_unknown_token_in_context_keeps_qss_valid():
    """The fallback substitutes inline so surrounding QSS stays parseable."""
    assert resolve("2px solid var(--missing)") == f"2px solid {_UNKNOWN_TOKEN_FALLBACK}"


def test_unknown_token_warns_once(caplog):
    """Repeated references to the same unknown token warn a single time."""
    import logging as _logging

    _warned_tokens.discard("--spammy")
    with caplog.at_level(_logging.WARNING, logger="kneespa.theme"):
        resolve("var(--spammy) var(--spammy) var(--spammy)")

    warnings = [r for r in caplog.records if "--spammy" in r.getMessage()]
    assert len(warnings) == 1


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
    assert "#176b9a" in rendered


_TYPE_SCALE = ("--text-2xs", "--text-xs", "--text-sm", "--text-base", "--text-md",
               "--text-lg", "--text-xl", "--text-2xl", "--text-3xl")


def _px(token):
    return int(resolve(token).replace("px", ""))


def test_type_scale_is_strictly_increasing():
    """Every step reads as a different volume; no two steps collapse together."""
    sizes = [_px(token) for token in _TYPE_SCALE]
    assert sizes == sorted(set(sizes)), dict(zip(_TYPE_SCALE, sizes))


def test_arm_length_text_stays_at_least_16px():
    """Readouts, labels and buttons use --text-sm or larger; only captions go below."""
    assert _px("--text-sm") >= 16
    assert _px("--text-base") >= 16
    assert _px("--text-2xs") >= 12  # eyebrows / units still legible


def _rgb(token):
    value = resolve(token).lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def test_danger_resolves_to_red_and_never_to_primary_blue():
    red, green, blue = _rgb("--color-danger")
    assert red > 2 * green and red > 2 * blue, resolve("--color-danger")
    assert resolve("--color-danger") != resolve("--color-primary")
    assert resolve("--color-danger-hover") != resolve("--color-primary-hover")


def test_success_resolves_to_green():
    red, green, blue = _rgb("--color-success")
    assert green > red and green > blue, resolve("--color-success")


def test_each_action_variant_has_its_own_qss_rule():
    rendered = load_app_qss()
    for variant in ("primary", "success", "danger", "destructive", "secondary", "ghost"):
        assert f'QPushButton[variant="{variant}"] {{' in rendered, variant
    # The legacy "danger renders as primary" selector list must not return.
    assert 'QPushButton[variant="primary"],\nQPushButton[variant="danger"]' not in rendered


def test_theme_asset_urls_resolve_to_bundled_files():
    rendered = load_app_qss()
    paths = re.findall(r'url\("([^"]+)"\)', rendered)
    assert paths, "expected themed sub-control images"
    for path in paths:
        assert os.path.isfile(path), path
    assert "url(theme:" not in rendered
