import os
import shutil
import subprocess
from typing import Any, Optional

from loguru import logger
from mcp.server.fastmcp import FastMCP

from app.config import config
from app.services import bgm, voice
from app.utils import utils

# Initialize FastMCP Server
mcp = FastMCP("MoneyPrinterTurbo")


def _mask_api_key(val: Any) -> str:
    """Safely mask API keys without exposing secrets in plain text."""
    if not val:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    if len(s) <= 8:
        return "***"
    return f"{s[:3]}...{s[-4:]}"


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(secret_term in lowered for secret_term in ("key", "secret", "token", "password"))


@mcp.tool()
def mpt_get_status() -> dict[str, Any]:
    """
    Get the overall system health, FFmpeg availability, and configuration status of LLM/TTS/material providers.
    Never exposes raw unmasked API keys.
    """
    ffmpeg_bin = utils.get_ffmpeg_binary()
    ffmpeg_available = False
    if ffmpeg_bin:
        if os.path.isabs(ffmpeg_bin) and os.path.isfile(ffmpeg_bin):
            ffmpeg_available = True
        elif shutil.which(ffmpeg_bin) is not None:
            ffmpeg_available = True
        else:
            try:
                res = subprocess.run(
                    [ffmpeg_bin, "-version"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                ffmpeg_available = (res.returncode == 0)
            except Exception:
                ffmpeg_available = False

    configured_llm = config.app.get("llm_provider", "openai")

    # Inspect configured status of various API keys
    elevenlabs_key = voice.get_elevenlabs_api_key()
    api_keys_configured = {
        "openai": bool(config.app.get("openai_api_key")),
        "moonshot": bool(config.app.get("moonshot_api_key")),
        "azure_openai": bool(config.app.get("azure_api_key")),
        "qwen": bool(config.app.get("qwen_api_key")),
        "gemini": bool(config.app.get("gemini_api_key")),
        "deepseek": bool(config.app.get("deepseek_api_key")),
        "claude": bool(config.app.get("claude_api_key")),
        "ollama_base_url": bool(config.app.get("ollama_base_url")),
        "pexels": bool(config.app.get("pexels_api_keys")),
        "pixabay": bool(config.app.get("pixabay_api_keys")),
        "siliconflow": bool(config.siliconflow.get("api_key")),
        "minimax": bool(config.minimax_tts.get("api_key")),
        "elevenlabs": bool(elevenlabs_key),
        "azure_speech": bool(config.azure.get("speech_key")),
    }

    return {
        "project_name": config.project_name,
        "version": config.project_version,
        "ffmpeg_available": ffmpeg_available,
        "configured_llm_provider": configured_llm,
        "voice_provider": config.app.get("voice_provider", "edge"),
        "whisper_model": config.whisper.get("model", "base"),
        "api_keys_configured": api_keys_configured,
    }


@mcp.tool()
def mpt_update_settings(key: str, value: Any) -> dict[str, Any]:
    """
    Update a configuration parameter and persist it safely to config.toml without overwriting or deleting other keys.
    Key can be dotted (e.g. 'ui.hide_log', 'azure.speech_key') or a top-level key in the app section (e.g. 'llm_provider').
    """
    try:
        sections = {
            "app": config.app,
            "azure": config.azure,
            "siliconflow": config.siliconflow,
            "minimax_tts": config.minimax_tts,
            "elevenlabs": config.elevenlabs,
            "chatterbox": config.chatterbox,
            "ui": config.ui,
            "whisper": config.whisper,
            "proxy": config.proxy,
        }

        if "." in key:
            section_name, sub_key = key.split(".", 1)
            if section_name in sections:
                sections[section_name][sub_key] = value
            elif section_name in config._cfg:
                if isinstance(config._cfg[section_name], dict):
                    config._cfg[section_name][sub_key] = value
                else:
                    config._cfg[key] = value
            else:
                config._cfg.setdefault(section_name, {})[sub_key] = value
        else:
            found = False
            for s_name, s_dict in sections.items():
                if key in s_dict:
                    s_dict[key] = value
                    found = True
                    break
            if not found:
                config.app[key] = value

        config.save_config()

        display_val = _mask_api_key(value) if _is_secret_key(key) else value
        return {
            "success": True,
            "key": key,
            "value": display_val,
            "message": f"Successfully updated and persisted setting '{key}'",
        }
    except Exception as e:
        logger.error(f"Error updating setting {key}: {e}")
        return {
            "success": False,
            "key": key,
            "error": str(e),
        }


@mcp.tool()
def mpt_list_voices(language: str = "") -> list[dict[str, Any]]:
    """
    List all supported TTS voices, optionally filtered by language or locale code (e.g. 'es', 'es-ES', 'en', 'zh').
    """
    voices: list[dict[str, Any]] = []

    # 1. Azure / Edge TTS voices
    for item in voice._load_azure_voices():
        v_name = item.get("name", "")
        v_gender = item.get("gender", "Unknown")
        full_name = f"{v_name}-{v_gender}"
        locale_parts = v_name.split("-")
        locale = f"{locale_parts[0]}-{locale_parts[1]}" if len(locale_parts) >= 2 else locale_parts[0]
        voices.append({
            "name": full_name,
            "gender": v_gender,
            "provider": "azure",
            "language": locale,
            "description": f"Azure/Edge-TTS ({locale})",
        })

    # 2. SiliconFlow voices
    for sv in voice.get_siliconflow_voices():
        gender = "Male" if sv.endswith("-Male") else "Female" if sv.endswith("-Female") else "Unknown"
        voices.append({
            "name": sv,
            "gender": gender,
            "provider": "siliconflow",
            "language": "zh",
            "description": f"SiliconFlow CosyVoice ({sv})",
        })

    # 3. Gemini voices
    for gv in voice.get_gemini_voices():
        gender = "Male" if gv.endswith("-Male") else "Female" if gv.endswith("-Female") else "Unknown"
        voices.append({
            "name": gv,
            "gender": gender,
            "provider": "gemini",
            "language": "en",
            "description": f"Gemini TTS ({gv})",
        })

    # 4. MiMo voices
    for mv in voice.get_mimo_voices():
        gender = "Male" if mv.endswith("-Male") else "Female" if mv.endswith("-Female") else "Unknown"
        voices.append({
            "name": mv,
            "gender": gender,
            "provider": "mimo",
            "language": "zh",
            "description": f"Xiaomi MiMo TTS ({mv})",
        })

    # 5. MiniMax voices
    for mm in voice.get_minimax_voices():
        voices.append({
            "name": mm,
            "gender": "Unknown",
            "provider": "minimax",
            "language": "multilingual",
            "description": f"MiniMax Speech-02 ({mm})",
        })

    # 6. Chatterbox voices
    for cb in voice.get_chatterbox_voices():
        gender = "Male" if cb.endswith("-Male") else "Female" if cb.endswith("-Female") else "Unknown"
        voices.append({
            "name": cb,
            "gender": gender,
            "provider": "chatterbox",
            "language": "multilingual",
            "description": f"Chatterbox self-hosted TTS ({cb})",
        })

    # 7. ElevenLabs voices if configured
    el_key = voice.get_elevenlabs_api_key()
    if el_key:
        for el in voice.get_elevenlabs_voices(el_key):
            voices.append({
                "name": el,
                "gender": "Unknown",
                "provider": "elevenlabs",
                "language": "multilingual",
                "description": f"ElevenLabs ({el})",
            })

    # 8. No-voice sentinel
    voices.append({
        "name": voice.NO_VOICE_NAME,
        "gender": "None",
        "provider": "system",
        "language": "all",
        "description": "Silent audio placeholder (no narration)",
    })

    if not language:
        return voices

    query = language.strip().lower()
    filtered: list[dict[str, Any]] = []
    for v in voices:
        v_name = v.get("name", "").lower()
        v_lang = v.get("language", "").lower()
        v_desc = v.get("description", "").lower()

        # Check match against language code, name or description
        if (
            query in v_lang
            or query in v_name
            or query in v_desc
            or v_lang == "all"
            or (query == "es" and ("es-" in v_name or "spanish" in v_desc))
            or (query == "en" and ("en-" in v_name or "english" in v_desc))
            or (query == "zh" and ("zh-" in v_name or "chinese" in v_desc))
        ):
            filtered.append(v)

    return filtered


@mcp.tool()
def mpt_list_fonts() -> list[str]:
    """
    List all available subtitle font files installed in the resource/fonts directory.
    """
    fonts: list[str] = []
    font_directory = utils.font_dir()
    if os.path.isdir(font_directory):
        for root, _, files in os.walk(font_directory):
            for file in files:
                if file.lower().endswith((".ttf", ".ttc", ".otf")):
                    fonts.append(file)
    fonts.sort()
    return fonts


@mcp.tool()
def mpt_list_bgm() -> list[str]:
    """
    List all available background music files in resource/songs and uploaded storage.
    """
    bgm_files = bgm.list_bgm_files()
    return [os.path.basename(f) for f in bgm_files]
