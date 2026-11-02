"""Tests for issue #41: Batch generation incremental progress and non-destructive UI updates."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDIO_BATCH_JS = ROOT / "demo" / "assets" / "studio-batch.js"
STUDIO_APP_JS = ROOT / "demo" / "assets" / "studio-app.js"
QUICK_CREATE_CSS = ROOT / "demo" / "assets" / "quick-create.css"


def test_busy_step_one_fallback_removed():
    """Verify that currentStep is never forcibly overridden to 1 when busy and 0."""
    content = STUDIO_BATCH_JS.read_text(encoding="utf-8")
    assert "if (busy && currentStep === 0) currentStep = 1;" not in content


def test_zero_emoji_in_batch_ui():
    """Verify studio-batch.js does not contain any emoji in code or UI text."""
    content = STUDIO_BATCH_JS.read_text(encoding="utf-8")
    emoji_pattern = re.compile(
        r"[\U0001F300-\U0001F64F\U0001F680-\U0001F6FF\U00002600-\U000026FF\U00002700-\U000027BF\U0001F900-\U0001F9FF\U0001F1E0-\U0001F1FF]"
    )
    match = emoji_pattern.search(content)
    assert match is None, f"Found forbidden emoji in studio-batch.js: {match.group() if match else None}"


def test_batch_controller_incremental_methods():
    """Verify BatchCreateController defines required incremental update and stopping methods."""
    content = STUDIO_BATCH_JS.read_text(encoding="utf-8")
    assert "formatProgressStatus(" in content
    assert "formatSummaryStatus(" in content
    assert "setStopping(" in content
    assert "updateProgress(" in content
    assert "appendResultCard(" in content


def test_studio_app_incremental_submission_and_error_handling():
    """Verify studio-app.js loops incrementally with global error bail-out and cancel support."""
    content = STUDIO_APP_JS.read_text(encoding="utf-8")

    # Incremental update during loop execution
    assert "window.HandrawBatchCreate.updateProgress(" in content

    # Global error detection (401, 402, 403, 429)
    assert "isGlobalError" in content
    assert "401|402|403|429" in content

    # Graceful stop hook
    assert "window.HandrawBatchCreate.setStopping" in content


def test_quick_create_css_classes():
    """Verify quick-create.css defines both busy and summary status styles."""
    content = QUICK_CREATE_CSS.read_text(encoding="utf-8")
    assert ".batch-busy-status" in content
    assert ".batch-summary-status" in content
