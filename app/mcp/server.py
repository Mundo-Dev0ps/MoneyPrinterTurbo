import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional, Union

from loguru import logger
from mcp.server.fastmcp import FastMCP

from app.config import config
from app.models import const
from app.models.schema import VideoAspect, VideoParams
from app.services import bgm, llm, material, subtitle, task_artifacts, voice
from app.services import state as sm
from app.utils import utils

# Initialize FastMCP Server
mcp = FastMCP("MoneyPrinterTurbo")


def _read_script_data(task_id: str) -> dict[str, Any]:
    """Safely read script.json data for a task."""
    target = Path(utils.task_dir(task_id)) / "script.json"
    if not target.exists():
        return {}
    try:
        with target.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"failed to read script data for {task_id}: {e}")
        return {}


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


@mcp.tool()
def mpt_create_task(
    subject: str,
    aspect: str = "9:16",
    language: str = "",
) -> dict[str, Any]:
    """
    Create a new video generation task and initialize storage/tasks/<task_id>/ with default VideoParams and script.json.
    """
    task_id = utils.get_uuid()
    task_dir = utils.task_dir(task_id)

    # Normalize aspect ratio
    aspect_val = aspect
    if aspect in ("9:16", "portrait"):
        aspect_val = VideoAspect.portrait.value
    elif aspect in ("16:9", "landscape"):
        aspect_val = VideoAspect.landscape.value
    elif aspect in ("1:1", "square"):
        aspect_val = VideoAspect.square.value

    params = VideoParams(
        video_subject=subject,
        video_aspect=aspect_val,
        video_language=language or "",
    )
    params_dict = params.model_dump() if hasattr(params, "model_dump") else params.dict()

    payload = {
        "script": "",
        "search_terms": [],
        "params": params_dict,
    }
    task_artifacts.write_script_data(task_id, payload)
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0, subject=subject)

    return {
        "success": True,
        "task_id": task_id,
        "task_dir": task_dir,
        "subject": subject,
        "aspect": aspect,
        "language": language,
        "params": params_dict,
    }


@mcp.tool()
def mpt_generate_script(
    task_id: str,
    subject: str = "",
    prompt_hint: str = "",
) -> dict[str, Any]:
    """
    Generate video script and search terms using the configured LLM provider and persist to script.json.
    """
    script_data = _read_script_data(task_id)
    params = script_data.get("params") or {}

    target_subject = (subject or params.get("video_subject") or "").strip()
    if not target_subject:
        return {
            "success": False,
            "task_id": task_id,
            "error": "Subject is required to generate script.",
        }

    language = params.get("video_language", "")
    paragraph_number = int(params.get("paragraph_number", 1))
    custom_system_prompt = params.get("custom_system_prompt", "")
    video_script_prompt = prompt_hint or params.get("video_script_prompt", "")

    try:
        video_script = llm.generate_script(
            video_subject=target_subject,
            language=language,
            paragraph_number=paragraph_number,
            video_script_prompt=video_script_prompt,
            custom_system_prompt=custom_system_prompt,
        )
    except Exception as e:
        logger.error(f"Error generating script: {e}")
        return {
            "success": False,
            "task_id": task_id,
            "error": f"Failed to generate script: {str(e)}",
        }

    if not video_script or "Error: " in video_script:
        err_msg = (
            video_script.removeprefix("Error: ").strip()
            if isinstance(video_script, str) and "Error: " in video_script
            else "Failed to generate video script"
        )
        return {
            "success": False,
            "task_id": task_id,
            "error": err_msg,
        }

    try:
        video_terms = llm.generate_terms(
            video_subject=target_subject,
            video_script=video_script,
            amount=5,
        )
    except Exception as e:
        logger.warning(f"Error generating terms: {e}")
        video_terms = []

    if subject:
        params["video_subject"] = subject
    if prompt_hint:
        params["video_script_prompt"] = prompt_hint

    task_artifacts.patch_script_data(
        task_id,
        script=video_script,
        search_terms=video_terms,
        params=params,
    )
    sm.state.patch_task(task_id, script=video_script, terms=video_terms, progress=10)

    return {
        "success": True,
        "task_id": task_id,
        "script": video_script,
        "search_terms": video_terms,
    }


@mcp.tool()
def mpt_update_script(
    task_id: str,
    script_text: str,
    terms: Union[list[str], str, None] = None,
) -> dict[str, Any]:
    """
    Update the script text and search terms in script.json and task state.
    """
    script_data = _read_script_data(task_id)

    formatted_terms: list[str] = []
    if isinstance(terms, str):
        formatted_terms = [t.strip() for t in re.split(r"[,，]", terms) if t.strip()]
    elif isinstance(terms, list):
        formatted_terms = [str(t).strip() for t in terms if str(t).strip()]
    elif terms is None:
        formatted_terms = script_data.get("search_terms") or []

    task_artifacts.patch_script_data(
        task_id,
        script=script_text,
        search_terms=formatted_terms,
    )
    sm.state.patch_task(task_id, script=script_text, terms=formatted_terms)

    return {
        "success": True,
        "task_id": task_id,
        "script": script_text,
        "search_terms": formatted_terms,
    }


@mcp.tool()
def mpt_synthesize_voice(
    task_id: str,
    voice_name: str = "",
    voice_rate: float = 1.0,
    voice_volume: float = 1.0,
) -> dict[str, Any]:
    """
    Synthesize narration audio (audio.mp3) from the task script using TTS.
    """
    script_data = _read_script_data(task_id)
    script_text = script_data.get("script", "").strip()
    if not script_text:
        return {
            "success": False,
            "task_id": task_id,
            "error": "No script found for task. Generate or update script first.",
        }

    params = script_data.get("params") or {}
    selected_voice = (
        voice_name
        or params.get("voice_name")
        or config.app.get("voice_name", "zh-CN-XiaoxiaoNeural-Female")
    )
    parsed_voice = voice.parse_voice_name(selected_voice)

    task_dir = utils.task_dir(task_id)
    audio_file = os.path.join(task_dir, "audio.mp3")

    try:
        sub_maker = voice.tts(
            text=script_text,
            voice_name=parsed_voice,
            voice_rate=voice_rate,
            voice_file=audio_file,
            voice_volume=voice_volume,
        )
    except Exception as e:
        logger.error(f"Error in TTS synthesis: {e}")
        return {
            "success": False,
            "task_id": task_id,
            "error": f"TTS synthesis failed: {str(e)}",
        }

    if not os.path.exists(audio_file) and sub_maker is None:
        return {
            "success": False,
            "task_id": task_id,
            "error": "Failed to generate audio file.",
        }

    raw_duration = 0.0
    if sub_maker is not None:
        raw_duration = voice.get_audio_duration(sub_maker)
    if raw_duration == 0.0 and os.path.exists(audio_file):
        raw_duration = voice.get_audio_duration(audio_file)

    audio_duration = math.ceil(raw_duration)

    task_artifacts.patch_script_data(
        task_id,
        audio_file=audio_file,
        audio_duration=audio_duration,
        voice_name=selected_voice,
        voice_rate=voice_rate,
        voice_volume=voice_volume,
    )
    sm.state.patch_task(
        task_id,
        audio_file=audio_file,
        audio_duration=audio_duration,
        progress=30,
    )

    return {
        "success": True,
        "task_id": task_id,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "voice_name": selected_voice,
        "voice_rate": voice_rate,
        "voice_volume": voice_volume,
    }


@mcp.tool()
def mpt_generate_subtitles(
    task_id: str,
    font_name: str = "STHeitiMedium.ttc",
    text_color: str = "#FFFFFF",
    font_size: int = 60,
    subtitle_position: str = "bottom",
) -> dict[str, Any]:
    """
    Generate subtitles (subtitle.srt) from audio/script and configure subtitle styling parameters.
    """
    script_data = _read_script_data(task_id)
    script_text = script_data.get("script", "")
    task_dir = utils.task_dir(task_id)
    audio_file = os.path.join(task_dir, "audio.mp3")
    subtitle_file = os.path.join(task_dir, "subtitle.srt")

    if not os.path.exists(subtitle_file) and os.path.exists(audio_file):
        try:
            subtitle_provider = config.app.get("subtitle_provider", "edge").strip().lower()
            if subtitle_provider == "whisper":
                subtitle.create(audio_file=audio_file, subtitle_file=subtitle_file)
                if script_text:
                    subtitle.correct(subtitle_file=subtitle_file, video_script=script_text)
            else:
                subtitle.create(audio_file=audio_file, subtitle_file=subtitle_file)
                if script_text and os.path.exists(subtitle_file):
                    subtitle.correct(subtitle_file=subtitle_file, video_script=script_text)
        except Exception as e:
            logger.warning(f"Could not automatically transcribe subtitles: {e}")

    subtitle_count = 0
    if os.path.exists(subtitle_file):
        try:
            sub_items = subtitle.file_to_subtitles(subtitle_file)
            subtitle_count = len(sub_items)
        except Exception as e:
            logger.warning(f"Error parsing subtitle lines: {e}")

    task_artifacts.patch_script_data(
        task_id,
        subtitle_path=subtitle_file,
        font_name=font_name,
        text_fore_color=text_color,
        font_size=font_size,
        subtitle_position=subtitle_position,
    )
    sm.state.patch_task(task_id, subtitle_path=subtitle_file, progress=40)

    return {
        "success": True,
        "task_id": task_id,
        "subtitle_file": subtitle_file,
        "font_name": font_name,
        "text_color": text_color,
        "font_size": font_size,
        "subtitle_position": subtitle_position,
        "subtitle_count": subtitle_count,
    }


@mcp.tool()
def mpt_fetch_materials(
    task_id: str,
    source: str = "pexels",
) -> dict[str, Any]:
    """
    Search and download video clips matching the search terms from stock providers (e.g. pexels, pixabay).
    """
    script_data = _read_script_data(task_id)
    search_terms = script_data.get("search_terms") or []
    if not search_terms:
        return {
            "success": False,
            "task_id": task_id,
            "error": "No search terms found in task. Generate or update script and search terms first.",
        }

    params = script_data.get("params") or {}
    aspect_str = params.get("video_aspect", VideoAspect.portrait.value)
    audio_duration = float(script_data.get("audio_duration") or 15.0)

    try:
        downloaded_videos = material.download_videos(
            task_id=task_id,
            search_terms=search_terms,
            source=source,
            video_aspect=aspect_str,
            audio_duration=audio_duration,
        )
    except Exception as e:
        logger.error(f"Error downloading materials: {e}")
        return {
            "success": False,
            "task_id": task_id,
            "error": f"Failed to download materials: {str(e)}",
        }

    if not downloaded_videos:
        return {
            "success": False,
            "task_id": task_id,
            "error": f"No video materials were downloaded from {source}.",
        }

    task_artifacts.patch_script_data(task_id, materials=downloaded_videos, video_source=source)
    sm.state.patch_task(task_id, materials=downloaded_videos, progress=50)

    return {
        "success": True,
        "task_id": task_id,
        "source": source,
        "materials": downloaded_videos,
        "material_count": len(downloaded_videos),
    }


@mcp.tool()
def mpt_inspect_materials(task_id: str) -> dict[str, Any]:
    """
    Inspect task artifacts (script, terms, downloaded materials and source info) with a scene breakdown.
    """
    script_data = _read_script_data(task_id)
    script_text = script_data.get("script", "")
    search_terms = script_data.get("search_terms") or []
    material_sources = script_data.get("material_sources") or []
    materials = script_data.get("materials") or []

    # If materials list is empty, look for any video files in the task directory
    task_dir = utils.task_dir(task_id)
    if not materials and os.path.isdir(task_dir):
        found_videos = []
        for file in sorted(os.listdir(task_dir)):
            if file.lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
                found_videos.append(os.path.join(task_dir, file))
        if found_videos:
            materials = found_videos

    total_scenes = max(len(search_terms), len(materials), len(material_sources), 1 if script_text else 0)
    scenes: list[dict[str, Any]] = []

    for i in range(total_scenes):
        scene: dict[str, Any] = {
            "scene_index": i,
            "term": search_terms[i] if i < len(search_terms) else "",
            "material_file": materials[i] if i < len(materials) else "",
            "source_info": material_sources[i] if i < len(material_sources) else None,
        }
        scenes.append(scene)

    return {
        "success": True,
        "task_id": task_id,
        "script": script_text,
        "search_terms": search_terms,
        "material_sources": material_sources,
        "downloaded_materials": materials,
        "scenes": scenes,
        "total_scenes": total_scenes,
    }


@mcp.tool()
def mpt_replace_scene_material(
    task_id: str,
    scene_index: int,
    search_query_or_file: str,
) -> dict[str, Any]:
    """
    Replace the video clip for a specific scene index with a local file or a newly downloaded stock clip.
    """
    script_data = _read_script_data(task_id)
    materials = list(script_data.get("materials") or [])
    task_dir = utils.task_dir(task_id)

    new_material_path = ""
    if os.path.isfile(search_query_or_file):
        dest_filename = f"scene_{scene_index}_{os.path.basename(search_query_or_file)}"
        dest_file = os.path.join(task_dir, dest_filename)
        try:
            if os.path.abspath(search_query_or_file) != os.path.abspath(dest_file):
                shutil.copyfile(search_query_or_file, dest_file)
            new_material_path = dest_file
        except Exception as e:
            logger.error(f"Error copying local file: {e}")
            new_material_path = search_query_or_file
    else:
        # Stock search query
        try:
            downloaded = material.download_videos(
                task_id=task_id,
                search_terms=[search_query_or_file],
                source="pexels",
                audio_duration=10.0,
            )
            if downloaded:
                new_material_path = downloaded[0]
            else:
                return {
                    "success": False,
                    "task_id": task_id,
                    "error": f"Failed to download material for query: '{search_query_or_file}'",
                }
        except Exception as e:
            logger.error(f"Error downloading replacement material: {e}")
            return {
                "success": False,
                "task_id": task_id,
                "error": f"Error downloading material: {str(e)}",
            }

    # Update materials list at scene_index
    if scene_index < len(materials):
        materials[scene_index] = new_material_path
    else:
        while len(materials) < scene_index:
            materials.append("")
        materials.append(new_material_path)

    task_artifacts.patch_script_data(task_id, materials=materials)
    sm.state.patch_task(task_id, materials=materials)

    return {
        "success": True,
        "task_id": task_id,
        "scene_index": scene_index,
        "new_material": new_material_path,
        "materials": materials,
    }
