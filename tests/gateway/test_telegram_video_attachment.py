"""Regression tests for Telegram inbound video attachments."""

from unittest.mock import patch

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource


def _make_runner():
    from gateway.run import GatewayRunner

    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig()
    runner.adapters = {}
    runner._model = "test-model"
    runner._base_url = ""
    runner._has_setup_skill = lambda: False
    return runner


@pytest.mark.asyncio
async def test_video_attachment_without_caption_gets_context_note():
    """A captionless Telegram video must not reach the agent as an empty message."""
    runner = _make_runner()
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = MessageEvent(
        text="",
        message_type=MessageType.VIDEO,
        source=source,
        media_urls=["/tmp/video_12345_squat.mp4"],
        media_types=["video/mp4"],
    )

    with patch("tools.credential_files.to_agent_visible_cache_path", side_effect=lambda p: p):
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
        )

    assert result is not None
    assert result.strip()
    assert "video attachment" in result.lower()
    assert "squat.mp4" in result
    assert "video_analyze" in result
    assert "/tmp/video_12345_squat.mp4" in result


@pytest.mark.asyncio
async def test_video_attachment_preserves_caption():
    """A captioned video should include both the saved path and the user's request."""
    runner = _make_runner()
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = MessageEvent(
        text="Разбери технику",
        message_type=MessageType.VIDEO,
        source=source,
        media_urls=["/tmp/video_12345_deadlift.mov"],
        media_types=["video/quicktime"],
    )

    with patch("tools.credential_files.to_agent_visible_cache_path", side_effect=lambda p: p):
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
        )

    assert result is not None
    assert "video attachment" in result.lower()
    assert "deadlift.mov" in result
    assert "Разбери технику" in result
