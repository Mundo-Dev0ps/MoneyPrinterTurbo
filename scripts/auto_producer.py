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
from app.utils import utils


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


def check_smart_slot_needed(data: dict) -> tuple[bool, str]:
    """
    Checks if a video needs to be produced based on today's slots and what has already run.
    Daily slots: ["10:30", "14:30", "19:30"]
    Returns (should_run, reason)
    """
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%H:%M")

    # Count how many videos were rendered/published today
    published_today = 0
    for topic in data.get("topics", []):
        rendered_at = topic.get("rendered_at")
        if rendered_at and rendered_at.startswith(today_str):
            published_today += 1

    settings = data.get("schedule_settings", {})
    daily_slots = sorted(settings.get("daily_slots", ["10:30", "14:30", "19:30"]))

    # Find how many slots should have occurred by now
    expected_slots_by_now = sum(1 for slot in daily_slots if current_time_str >= slot)

    if expected_slots_by_now == 0:
        return False, f"Aún no es la hora del primer slot de hoy ({daily_slots[0]}). Hora actual: {current_time_str}"

    if published_today < expected_slots_by_now:
        return True, f"Slot pendiente detectado: Deberían haberse publicado {expected_slots_by_now} video(s) a las {current_time_str}, pero van {published_today}."

    return False, f"Al día: Hoy ya se publicaron {published_today}/{len(daily_slots)} videos correspondientes a la hora actual ({current_time_str})."


def refill_topics_if_needed(data: dict, min_pending: int = 3, batch_size: int = 10) -> int:
    """
    If pending topics count drops below min_pending, automatically uses Gemini LLM
    to brainstorm and append new high-retention viral topics following our winning formula.
    """
    pending_count = sum(1 for t in data.get("topics", []) if t.get("status") == "pending")
    if pending_count >= min_pending:
        return 0

    logger.info(f"Quedan solo {pending_count} temas pendientes. Autogenerando {batch_size} nuevos temas virales con Gemini LLM...")
    
    # Extract existing subjects to avoid duplicates
    existing_subjects = [t.get("subject", "") for t in data.get("topics", [])]
    existing_list_str = "\n- ".join(existing_subjects[-30:])

    prompt = f"""Eres un creador de contenido experto en YouTube Shorts virales de ciencia, megaterremotos, misterios cósmicos y curiosidades de la Tierra.
Genera exactamente {batch_size} NUEVOS temas virales de alto impacto y retención, alternando entre:
1. Megaterremotos históricos, sismos extremos, fallas geológicas colosales (Cascadia, San Andrés, Valdivia, Cinturón de Fuego)
2. Misterios y curiosidades del cosmos (agujeros negros, supernovas, planetas extraños)
3. Secretos geológicos y abismales de la Tierra (fosas submarinas, supervolcanes, fenómenos inexplicables)
4. "¿Qué pasaría si...?" (experimentos mentales extremos de física y geología)

IMPORTANTE:
- NO repitas ninguno de estos temas que ya hicimos:
- {existing_list_str}

Responde ÚNICAMENTE con un JSON válido que sea una lista de objetos con esta estructura exacta (sin texto adicional):
[
  {{
    "subject": "Título atractivo y con gancho (sin emojis)",
    "category": "Megaterremotos & Sismos / Cosmos & Espacio / Misterios Abisales / Secretos de la Tierra / Que pasaria si",
    "script": "Guion completo en español narrativo continuo de 60 a 75 palabras. Debe empezar con un gancho demoledor en la primera frase, desarrollar el misterio o dato científico con máxima tensión y terminar obligatoriamente con una pregunta potente seguida del llamado a la acción: '¿Qué opinas? ¡Déjamelo saber en los comentarios!' o '¿Crees que podría ocurrir pronto? ¡Déjalo en los comentarios!'.",
    "search_terms": [
      "4 or 5 descriptive english search keywords for stock footage in pexels",
      "earthquake cracked ground seismic",
      "space galaxy planet dark"
    ],
    "tags": ["shorts", "terremoto", "ciencia", "misterios", "curiosidades", "erdivertido"]
  }}
]"""

    try:
        from app.services import llm
        response_text = llm.generate_response(prompt=prompt)
        
        # Clean JSON block
        clean_json = response_text.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0].strip()
            
        new_topics = json.loads(clean_json)
        if not isinstance(new_topics, list):
            logger.warning("LLM response did not contain a valid list of topics.")
            return 0
            
        # Get max existing index
        max_idx = 0
        for t in data.get("topics", []):
            t_id = t.get("id", "")
            if t_id.startswith("topic_"):
                try:
                    num = int(t_id.replace("topic_", ""))
                    if num > max_idx:
                        max_idx = num
                except ValueError:
                    pass
                    
        added = 0
        for item in new_topics:
            max_idx += 1
            new_id = f"topic_{max_idx:03d}"
            item["id"] = new_id
            item["status"] = "pending"
            data["topics"].append(item)
            added += 1
            logger.info(f"Nuevo tema agregado a la cola: [{new_id}] {item.get('subject')}")
            
        save_topics_data(data)
        logger.info(f"Se agregaron {added} nuevos temas virales automaticamente a topics.json.")
        return added
    except Exception as e:
        logger.error(f"Error autogenerando temas con LLM: {e}")
        return 0


def run_production(auto_publish: bool = True, smart_check: bool = False) -> dict:
    logger.info("=== INICIANDO AUTO-PRODUCER MONEYPRINTERTURBO ===")
    data = load_topics_data()
    settings = data.get("schedule_settings", {})
    
    # Auto-refill queue with new viral topics if running low
    refill_topics_if_needed(data, min_pending=3, batch_size=10)
    
    if smart_check:
        should_run, reason = check_smart_slot_needed(data)
        logger.info(f"Smart Check: {reason}")
        if not should_run:
            return {"success": True, "skipped": True, "reason": reason}
    
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
    
    # 4. Generación de Subtítulos Dinámicos Karaoke (Amarillo + Blanco + Borde Negro)
    sub_res = mpt_generate_subtitles(
        task_id=task_id,
        font_name=settings.get("font_name", "BeVietnamPro-Bold.ttf"),
        font_size=settings.get("font_size", 70),
        stroke_color=settings.get("stroke_color", "#000000"),
        stroke_width=settings.get("stroke_width", 6),
        text_color=settings.get("text_color", "#FFFFFF"),
        text_background_color="",
        rounded_subtitle_background=False,
        subtitle_position="bottom",
        custom_position=58.0
    )
    # QA Check 1: Validar que el archivo de subtítulos (.srt) existe y no está vacío
    task_dir = os.path.join(utils.task_dir(), task_id)
    srt_file = os.path.join(task_dir, "subtitle.srt")
    if not os.path.isfile(srt_file) or os.path.getsize(srt_file) < 30:
        raise RuntimeError(f"QA GATE FAILED: El archivo de subtítulos {srt_file} no existe o está vacío. Abortando producción para evitar video sin subtítulos.")
    logger.info(f"QA GATE PASSED: Subtítulos verificados ({os.path.getsize(srt_file)} bytes).")
    
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
    if not video_path or not os.path.isfile(video_path) or os.path.getsize(video_path) < 1_000_000:
        raise RuntimeError(f"QA GATE FAILED: El video generado no existe o pesa menos de 1MB: {video_path}")
    logger.info(f"QA GATE PASSED: Video final verificado ({os.path.getsize(video_path)/(1024*1024):.2f} MB).")
    
    # 7. Publicación en YouTube
    upload_result = None
    if auto_publish:
        try:
            logger.info("Iniciando publicación en YouTube...")
            clean_subject = subject.strip()
            if "#shorts" not in clean_subject.lower():
                youtube_title = f"{clean_subject[:80]} #Shorts"
            else:
                youtube_title = clean_subject[:95]
            youtube_desc = f"{script_text}\n\n¿Qué opinas? ¡Déjamelo saber en los comentarios y suscríbete para más curiosidades! 👇\n\n" + " ".join(f"#{t}" for t in tags)
            
            youtube_extra = {
                "youtube_title": youtube_title,
                "youtube_description": youtube_desc,
                "tags": tags,
                "privacyStatus": "public",
                "containsSyntheticMedia": "true"
            }
            
            target_user = topic.get("user_name") or settings.get("upload_post_username")
            target_platforms = settings.get("platforms", ["youtube"])
            upload_result = ups.upload_video(
                video_path=video_path,
                title=youtube_title,
                platforms=target_platforms,
                youtube_extra=youtube_extra,
                user_name=target_user
            )
            logger.info(f"Resultado de publicación en {target_platforms}: {upload_result}")
        except Exception as e:
            logger.error(f"Error publicando en {target_platforms}: {e}")
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
    smart_mode = "--smart" in sys.argv
    result = run_production(auto_publish=auto_pub, smart_check=smart_mode)
    print(json.dumps(result, indent=2, ensure_ascii=False))
