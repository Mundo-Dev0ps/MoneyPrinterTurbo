import pytest
from app.mcp.server import (
    mpt_get_status,
    mpt_update_settings,
    mpt_list_voices,
    mpt_list_fonts,
    mpt_list_bgm,
)


def test_mpt_get_status():
    status = mpt_get_status()
    assert isinstance(status, dict)
    assert "ffmpeg_available" in status
    assert "configured_llm_provider" in status
    assert "api_keys_configured" in status
    assert isinstance(status["ffmpeg_available"], bool)
    assert isinstance(status["api_keys_configured"], dict)


def test_mpt_get_status_security():
    status = mpt_get_status()
    # Ensure api_keys_configured only contains booleans and no plain text secrets
    for provider, is_cfg in status["api_keys_configured"].items():
        assert isinstance(is_cfg, bool)


def test_mpt_list_voices():
    # Test with language filter
    voices_es = mpt_list_voices(language="es")
    assert isinstance(voices_es, list)
    assert len(voices_es) > 0
    assert any(
        "es-" in v.get("name", "").lower() or "spanish" in v.get("name", "").lower()
        for v in voices_es
    )

    # Test without language filter (all voices)
    voices_all = mpt_list_voices(language="")
    assert isinstance(voices_all, list)
    assert len(voices_all) > len(voices_es)


def test_mpt_list_fonts():
    fonts = mpt_list_fonts()
    assert isinstance(fonts, list)
    assert len(fonts) > 0
    assert any("STHeiti" in f or "YaHei" in f for f in fonts)


def test_mpt_list_bgm():
    songs = mpt_list_bgm()
    assert isinstance(songs, list)
    assert len(songs) > 0
    assert any(s.endswith(".mp3") for s in songs)


def test_mpt_update_settings():
    res = mpt_update_settings(key="ui.hide_log", value=False)
    assert isinstance(res, dict)
    assert res.get("success") is True
    assert res.get("key") == "ui.hide_log"
