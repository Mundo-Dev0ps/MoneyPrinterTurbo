#!/usr/bin/env python3
"""
Auto Producer Pipeline for MoneyPrinterTurbo
Executes automated Shorts generation and publication based on config/topics.json.
"""

import os
import sys
import json
import time
from datetime import datetime
from loguru import logger

# Add repo root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.mcp.server import (
    mpt_create_task,
    mpt_update_script,
    mpt_synthesize_voice,
    mpt_generate_subtitles,
    mpt_fetch_materials,
    mpt_render_video,
)
from app.services.upload_post import UploadPostService


TOPICS_FILE = os.path.join(PROJECT_ROOT, "config", "topics.json")


def load_topics_data() -> dict:
    if not os.path.isfile(TOPICS_FILE):
        raise FileNotFoundError(f"Topics database not found at {TOPICS_FILE}")
    with open(TOPICS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_topics_data(data: dict):
    # Atomic write
    temp_file = f"{TOPICS_FILE}.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temp_file, TOPICS_FILE)


def get_next_pending_topic(data: dict) -> dict | None:
    for topic in data.get("topics", []):
        if topic.get("status") == "pending":
            return topic
    return None


def run_production(auto_publish: bool = True) -> dict:
    logger.info("=== INICIANDO AUTO-PRODUCER MONEYPRINTERTURBO ===")
    data = load_topics_data()
    settings = data.get("schedule_settings", {})
    
    topic = get_next_pending_topic(data)
    if not topic:
        logger.warning("No hay más temas pendientes en config/topics.json.")
        return {"success": False, "message": "No pending topics found"}
    
    topic_id = topic["id"]
    subject = topic["subject"]
    script_text = topic["script"]
    terms = topic.get("search_terms", [])
    tags = topic.get("tags", [])
    
    logger.info(f"Produciendo tema: [{topic_id}] {subject}")
    
    # 1. Crear Tarea
    task = mpt_create_task(
        subject=subject,
        aspect=settings.get("aspect", "9:16"),
        language="es"
    )
    task_id = task["task_id"]
    logger.info(f"Tarea creada: {task_id}")
    
    # 2. Guardar Guion y Términos de Búsqueda
    mpt_update_script(task_id=task_id, script_text=script_text, terms=terms)
    logger.info("Guion y términos actualizados.")
    
    # 3. Síntesis de Voz
    voice_name = settings.get("voice_name", "gemini:Charon-Male")
    voice_res = mpt_synthesize_voice(task_id=task_id, voice_name=voice_name)
    logger.info(f"Voz sintetizada con {voice_name}: {voice_res}")
    
    # 4. Generación de Subtítulos Premium
    sub_res = mpt_generate_subtitles(
        task_id=task_id,
        font_name=settings.get("font_name", "BeVietnamPro-Bold.ttf"),
        font_size=settings.get("font_size", 75),
        stroke_color=settings.get("stroke_color", "#000000"),
        stroke_width=settings.get("stroke_width", 2.5),
        text_color=settings.get("text_color", "#FFFFFF"),
        text_background_color="#000000",
        rounded_subtitle_background=settings.get("rounded_subtitle_background", True),
        subtitle_position="bottom",
        custom_position=72.0
    )
    logger.info("Subtítulos generados con estilo premium.")
    
    # 5. Descarga de Materiales 4K (Pexels)
    mat_res = mpt_fetch_materials(task_id=task_id, source="pexels")
    logger.info(f"Materiales descargados: {mat_res}")
    
    # 6. Renderizado con Smart Full-Screen Cover (Cero Barras Negras)
    clip_dur = settings.get("clip_duration", 2)
    render_res = mpt_render_video(
        task_id=task_id,
        bgm_name="random",
        bgm_volume=0.10,
        video_clip_duration=clip_dur
    )
    logger.info(f"Render final completado: {render_res}")
    
    video_path = render_res["videos"][0] if render_res.get("videos") else None
    if not video_path or not os.path.isfile(video_path):
        raise RuntimeError(f"El video generado no existe en la ruta: {video_path}")
    
    # 7. Publicación en YouTube
    upload_result = None
    if auto_publish:
        try:
            logger.info("Iniciando publicación en YouTube...")
            ups = UploadPostService()
            youtube_title = f"{subject[:75]} 😱 #Shorts"
            youtube_desc = f"{script_text}\n\n¿Qué opinas? ¡Comenta tu respuesta! 👇\n\n" + " ".join(f"#{t}" for t in tags)
            
            youtube_extra = {
                "youtube_title": youtube_title,
                "youtube_description": youtube_desc,
                "tags": tags,
                "privacyStatus": "public",
                "containsSyntheticMedia": "true"
            }
            
            target_user = topic.get("user_name") or settings.get("upload_post_username")
            upload_result = ups.upload_video(
                video_path=video_path,
                title=youtube_title,
                platforms=["youtube"],
                youtube_extra=youtube_extra,
                user_name=target_user
            )
            logger.info(f"Resultado de publicación: {upload_result}")
        except Exception as e:
            logger.error(f"Error publicando en YouTube: {e}")
            upload_result = {"success": False, "error": str(e)}
    
    # 8. Actualizar topics.json
    now_str = datetime.now().isoformat()
    topic["status"] = "published" if upload_result and upload_result.get("success") else "rendered"
    topic["rendered_at"] = now_str
    topic["task_id"] = task_id
    topic["video_path"] = video_path
    topic["upload_result"] = upload_result
    
    save_topics_data(data)
    logger.info(f"Tema [{topic_id}] actualizado exitosamente en topics.json.")
    
    return {
        "success": True,
        "topic_id": topic_id,
        "subject": subject,
        "task_id": task_id,
        "video_path": video_path,
        "upload_result": upload_result
    }


if __name__ == "__main__":
    auto_pub = "--no-publish" not in sys.argv
    result = run_production(auto_publish=auto_pub)
    print(json.dumps(result, indent=2, ensure_ascii=False))
