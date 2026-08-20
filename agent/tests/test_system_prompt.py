"""System prompt variant selection and the deliberate omissions.

The omission tests are the important ones. If someone hardens the baseline
prompt against prompt injection, or makes it append terms and conditions, the
platform guardrails those exercises are meant to measure become untestable and
every participant scores a false pass.
"""

from __future__ import annotations

from system_prompt import (
    BASELINE_PROMPT,
    BROKEN_BETA_1,
    BROKEN_BETA_2,
    select_prompt,
    with_caller,
)


class TestSelectPrompt:
    def test_default_is_baseline(self) -> None:
        assert select_prompt(None) is BASELINE_PROMPT
        assert select_prompt("baseline") is BASELINE_PROMPT

    def test_broken_variants(self) -> None:
        assert select_prompt("broken") is BROKEN_BETA_1
        assert select_prompt("broken-2") is BROKEN_BETA_2

    def test_unknown_falls_back_silently(self) -> None:
        # A typo in SYSTEM_PROMPT_VARIANT must never stop the container booting.
        assert select_prompt("garbage") is BASELINE_PROMPT
        assert select_prompt("   ") is BASELINE_PROMPT

    def test_case_insensitive(self) -> None:
        assert select_prompt("BROKEN") is BROKEN_BETA_1
        assert select_prompt("BaSeLiNe") is BASELINE_PROMPT


class TestBaselineGrounding:
    """The baseline must instruct grounding, or the broken variants have
    nothing to regress away from and the quality evaluation has no signal."""

    def test_forbids_invention(self) -> None:
        assert "Never invent" in BASELINE_PROMPT

    def test_requires_iso_dates(self) -> None:
        assert "YYYY-MM-DD" in BASELINE_PROMPT

    def test_broken_variants_drop_grounding(self) -> None:
        assert "Never invent" not in BROKEN_BETA_1
        assert "Never invent" not in BROKEN_BETA_2


class TestDeliberateOmissions:
    """FIXTURE INTEGRITY. See the module docstring in system_prompt.py."""

    def test_no_injection_hardening_in_any_variant(self) -> None:
        for prompt in (BASELINE_PROMPT, BROKEN_BETA_1, BROKEN_BETA_2):
            lowered = prompt.lower()
            assert "ignore previous instructions" not in lowered
            assert "prompt injection" not in lowered

    def test_no_terms_and_conditions_instruction(self) -> None:
        for prompt in (BASELINE_PROMPT, BROKEN_BETA_1, BROKEN_BETA_2):
            lowered = prompt.lower()
            assert "terms and conditions" not in lowered


class TestWithCaller:
    def test_no_identity_returns_prompt_unchanged(self) -> None:
        assert with_caller(BASELINE_PROMPT, None, None) is BASELINE_PROMPT

    def test_identity_is_appended(self) -> None:
        out = with_caller(BASELINE_PROMPT, "Priya Raman", "guest-priya")
        assert "Priya Raman" in out
        assert "guest-priya" in out
        assert out.startswith(BASELINE_PROMPT)

    def test_name_only(self) -> None:
        assert "Priya Raman" in with_caller(BASELINE_PROMPT, "Priya Raman", None)
