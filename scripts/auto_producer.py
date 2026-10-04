#!/usr/bin/env python3
"""
Auto Producer Pipeline for MoneyPrinterTurbo
Executes automated Shorts generation and publication based on config/topics.json.
"""

import os
import sys
import json
import re
import time
from datetime import datetime
from loguru import logger

# Add repo root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.mcp.server import (  # noqa: E402
    mpt_create_task,
    mpt_update_script,
    mpt_synthesize_voice,
    mpt_generate_subtitles,
    mpt_fetch_materials,
    mpt_render_video,
)
from app.services.upload_post import UploadPostService  # noqa: E402
from app.utils import utils  # noqa: E402


TOPICS_FILE = os.path.join(PROJECT_ROOT, "config", "topics.json")
RETENTION_EDITORIAL_VERSION = "retention-v1"
RETENTION_PAUSE_TAG = "[pause:0.4]"


def _spoken_word_count(script_text: str) -> int:
    """Cuenta palabras habladas ignorando etiquetas de pausa como [pause:0.4]."""
    clean = re.sub(r"\[pause:[^\]]+\]", " ", script_text)
    return len([w for w in clean.split() if w])


def validate_topic_for_production(topic: dict) -> None:
    """
    Valida que un tema cumpla el contrato editorial correspondiente.
    Si no tiene 'editorial_version' o no es 'retention-v1', se trata como tema histórico y pasa.
    Para temas 'retention-v1', valida estrictamente cada regla editorial requerida.
    """
    if topic.get("editorial_version") != RETENTION_EDITORIAL_VERSION:
        return

    # 1. Validación de youtube_title
    yt_title = topic.get("youtube_title")
    if not yt_title or not isinstance(yt_title, str):
        raise ValueError(
            "El campo 'youtube_title' es obligatorio para temas retention-v1."
        )
    clean_title = yt_title.strip()
    if len(clean_title) < 35 or len(clean_title) > 55:
        raise ValueError(
            f"El campo 'youtube_title' debe tener entre 35 y 55 caracteres (actual: {len(clean_title)})."
        )
    if "#shorts" in clean_title.lower():
        raise ValueError(
            "El campo 'youtube_title' no debe contener la etiqueta #Shorts."
        )
    if ":" in clean_title:
        raise ValueError(
            "El campo 'youtube_title' no debe usar el formato 'Nombre: explicación' (contiene ':')."
        )

    # 2. Validación de script
    script = topic.get("script")
    if not script or not isinstance(script, str):
        raise ValueError("El campo 'script' es obligatorio para temas retention-v1.")

    words_count = _spoken_word_count(script)
    if words_count < 45 or words_count > 55:
        raise ValueError(
            f"El guion debe tener entre 45 y 55 palabras habladas (actual: {words_count})."
        )

    script_lower = script.lower()

    # Intros y saludos prohibidos
    forbidden_intros = ["hola", "bienvenidos", "en este video", "en el corazón de"]
    for fi in forbidden_intros:
        if fi in script_lower:
            raise ValueError(
                f"El guion contiene introducción o saludo prohibido: '{fi}'."
            )

    # CTAs fijos prohibidos
    forbidden_ctas = [
        "déjamelo saber en los comentarios",
        "dejame en los comentarios",
        "¿qué opinas?",
        "¿que opinas?",
        "suscríbete",
        "suscribete",
        "comenta",
    ]
    for fc in forbidden_ctas:
        if fc in script_lower:
            raise ValueError(
                f"El guion contiene llamado a la acción fijo prohibido: '{fc}'."
            )

    # Pausas
    pause_tags = re.findall(r"\[pause:[^\]]+\]", script)
    if len(pause_tags) > 1:
        raise ValueError(
            f"El guion solo puede tener como máximo una pausa (detectadas: {len(pause_tags)})."
        )
    if len(pause_tags) == 1:
        if pause_tags[0] != RETENTION_PAUSE_TAG:
            raise ValueError(
                f"La pausa debe ser exactamente '{RETENTION_PAUSE_TAG}', encontrada: '{pause_tags[0]}'."
            )
        # La pausa debe ubicarse inmediatamente después del gancho inicial
        pre_pause = script.split(RETENTION_PAUSE_TAG)[0].strip()
        if not re.search(r"[.!?]$", pre_pause):
            raise ValueError(
                "La pausa [pause:0.4] debe ubicarse inmediatamente después del gancho inicial (tras un punto o signo)."
            )
        inner_pre = pre_pause[:-1]
        if re.search(r"[.!?]", inner_pre):
            raise ValueError(
                "La pausa [pause:0.4] debe ubicarse inmediatamente después del gancho inicial (no en oraciones posteriores)."
            )

    # Gancho inicial (primera oración)
    hook_segment = (
        script.split(RETENTION_PAUSE_TAG)[0].strip()
        if RETENTION_PAUSE_TAG in script
        else script
    )
    sentence_match = re.search(r"^([^.!?]+[.!?])", hook_segment)
    hook_text = sentence_match.group(1).strip() if sentence_match else hook_segment
    hook_words = len(
        [w for w in re.sub(r"\[pause:[^\]]+\]", "", hook_text).split() if w]
    )
    if hook_words > 8:
        raise ValueError(
            f"El gancho inicial debe tener 8 palabras o menos (actual: {hook_words} palabras: '{hook_text}')."
        )

    # 3. Validación de search_terms
    terms = topic.get("search_terms")
    if not terms or not isinstance(terms, list) or len(terms) != 5:
        count = len(terms) if isinstance(terms, list) else 0
        raise ValueError(
            f"El campo 'search_terms' debe contener exactamente 5 términos de búsqueda (actual: {count})."
        )

    lowered_terms = set()
    for i, term in enumerate(terms):
        if not isinstance(term, str):
            raise ValueError(
                f"El término de búsqueda {i + 1} en 'search_terms' debe ser un string."
            )
        term_words = len(term.strip().split())
        if term_words < 4 or term_words > 8:
            raise ValueError(
                f"El término de búsqueda '{term}' en 'search_terms' debe tener entre 4 y 8 palabras (actual: {term_words})."
            )
        t_low = term.strip().lower()
        if t_low in lowered_terms:
            raise ValueError(
                f"El término de búsqueda '{term}' en 'search_terms' está duplicado."
            )
        lowered_terms.add(t_low)


def prepare_script_text(topic: dict) -> str:
    """
    Prepara el guion para síntesis y renderizado.
    Temas retention-v1 conservan su guion y pausa [pause:0.4] intactos.
    Temas históricos usan ensure_dramatic_pauses() agregando [pause:0.6].
    """
    if topic.get("editorial_version") == RETENTION_EDITORIAL_VERSION:
        return topic.get("script", "")
    return ensure_dramatic_pauses(topic.get("script", ""))


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
        return (
            False,
            f"Aún no es la hora del primer slot de hoy ({daily_slots[0]}). Hora actual: {current_time_str}",
        )

    if published_today < expected_slots_by_now:
        return (
            True,
            f"Slot pendiente detectado: Deberían haberse publicado {expected_slots_by_now} video(s) a las {current_time_str}, pero van {published_today}.",
        )

    return (
        False,
        f"Al día: Hoy ya se publicaron {published_today}/{len(daily_slots)} videos correspondientes a la hora actual ({current_time_str}).",
    )


def refill_topics_if_needed(
    data: dict, min_pending: int = 3, batch_size: int = 10
) -> int:
    """
    If pending topics count drops below min_pending, automatically uses Gemini LLM
    to brainstorm and append new high-retention viral topics following our winning formula.
    """
    pending_count = sum(
        1 for t in data.get("topics", []) if t.get("status") == "pending"
    )
    if pending_count >= min_pending:
        return 0

    logger.info(
        f"Quedan solo {pending_count} temas pendientes. Autogenerando {batch_size} nuevos temas virales con Gemini LLM..."
    )

    # Extract all existing subjects and core keywords to avoid duplicates
    existing_subjects = [
        t.get("subject", "").strip() for t in data.get("topics", []) if t.get("subject")
    ]
    existing_list_str = "\n- ".join(existing_subjects)

    prompt = f"""Eres un creador de contenido experto en YouTube Shorts virales de ciencia, catástrofes históricas, megaterremotos y misterios abisales del océano.
Genera exactamente {batch_size} NUEVOS temas virales de altísima retención e intriga visual, alternando entre:
1. Grandes terremotos y megatsunamis históricos o zonas de subducción activas poco exploradas
2. Anomalías abisales oceánicas, fosas inexploradas y criaturas de aguas profundas extremas
3. Enigmas astrofísicos reales, impactos de asteroides y colisiones cósmicas
4. Procesos geológicos colosales (fosas tectónicas submarinas, calderas activas, emanaciones hidrotermales extremas)
PROHIBIDO generar temas hipotéticos abstractos tipo "¿Qué pasaría si...?" porque carecen de imágenes reales de stock.

CRÍTICO - CONTROL ESTRICTO ANTI-DUPLICIDAD:
Está TERMINANTEMENTE PROHIBIDO repetir temas, lugares o eventos ya cubiertos.
Lista COMPLETA de temas que YA HICIMOS (NO REPETIR NINGUNO):
- {existing_list_str}

REGLAS EDITORIALES ESTRICTAS FORMATO retention-v1:
1. "editorial_version": Debe ser "retention-v1".
2. "youtube_title": Entre 35 y 55 caracteres. Una sola promesa o anomalía concreta. Sin formato 'Nombre: explicación' (sin ':'). NUNCA incluyas '#Shorts'.
3. "script": Exactamente entre 45 y 55 palabras habladas (excluyendo la etiqueta de pausa).
   - El primer enunciado es un gancho potente de 8 palabras o menos, terminado en punto.
   - Justo después del gancho, incluye exactamente una pausa: '[pause:0.4]'.
   - Sin saludos, sin 'hola', sin 'bienvenidos', sin 'en este video', sin 'en el corazón de'.
   - Desarrolla una sola idea y concluye con una revelación concreta.
   - NUNCA incluyas llamadas a la acción fijas como 'déjamelo saber en los comentarios', '¿qué opinas?' ni 'suscríbete'.
4. "search_terms": Exactamente 5 términos de búsqueda en inglés, específicos para metraje en 4K.
   - Cada término debe tener entre 4 y 8 palabras en inglés.
   - Todos los términos deben ser diferentes y representar escenas distintas. El primer término debe representar el gancho.

Responde ÚNICAMENTE con un JSON válido que sea una lista de objetos con esta estructura exacta (sin texto adicional):
[
  {{
    "editorial_version": "retention-v1",
    "youtube_title": "Título conciso y potente entre 35 y 55 caracteres",
    "subject": "Tema descriptivo para archivo",
    "category": "Megaterremotos & Sismos / Misterios Abisales / Cosmos Extremo / Secretos Geológicos",
    "script": "Gancho corto de ocho palabras. [pause:0.4] Desarrollo narrativo de una sola idea que suma entre 45 y 55 palabras en total.",
    "search_terms": [
      "four to eight english search words for hook",
      "four to eight english search words scene two",
      "four to eight english search words scene three",
      "four to eight english search words scene four",
      "four to eight english search words scene five"
    ],
    "tags": ["shorts", "ciencia", "misterios", "curiosidades", "erdivertido"]
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

        def _is_duplicate(new_title: str, past_titles: list[str]) -> bool:
            stop = {
                "el",
                "la",
                "los",
                "las",
                "un",
                "una",
                "unos",
                "unas",
                "de",
                "del",
                "en",
                "a",
                "al",
                "con",
                "por",
                "para",
                "que",
                "y",
                "o",
                "se",
                "su",
                "sus",
                "mas",
                "lo",
            }

            def norm(s):
                return [
                    w
                    for w in re.sub(r"[^\w\s]", " ", s.lower()).split()
                    if w not in stop and len(w) > 2
                ]

            new_tokens = set(norm(new_title))
            for pt in past_titles:
                pt_tokens = set(norm(pt))
                overlap = new_tokens.intersection(pt_tokens)
                if len(overlap) >= 3:
                    return True
            return False

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
        all_current_subjects = [t.get("subject", "") for t in data.get("topics", [])]
        for item in new_topics:
            subj = item.get("subject", "").strip()
            if not subj:
                continue
            if _is_duplicate(subj, all_current_subjects):
                logger.warning(
                    f"Descartando tema duplicado detectado por filtro anti-repetición: '{subj}'"
                )
                continue

            item["editorial_version"] = RETENTION_EDITORIAL_VERSION
            try:
                validate_topic_for_production(item)
            except ValueError as e:
                logger.warning(
                    f"Descartando tema generado inválido para retention-v1: {e}"
                )
                continue

            max_idx += 1
            new_id = f"topic_{max_idx:03d}"
            item["id"] = new_id
            item["status"] = "pending"
            data["topics"].append(item)
            all_current_subjects.append(subj)
            added += 1
            logger.info(f"Nuevo tema agregado a la cola: [{new_id}] {subj}")

        save_topics_data(data)
        logger.info(
            f"Se agregaron {added} nuevos temas virales automaticamente a topics.json."
        )
        return added
    except Exception as e:
        logger.error(f"Error autogenerando temas con LLM: {e}")
        return 0


def ensure_dramatic_pauses(script_text: str) -> str:
    """
    Garantiza que el guion tenga pausas dramáticas [pause:0.6] para generar suspenso y retención.
    Si el guion no tiene pausas, inserta una automáticamente tras la primera frase gancho.
    """
    if "[pause:" in script_text:
        return script_text

    import re

    match = re.search(r"([.!?])\s+", script_text)
    if match:
        idx = match.end()
        return script_text[:idx] + "[pause:0.6] " + script_text[idx:]
    return script_text


def resolve_topic_voice(topic: dict, settings: dict) -> str:
    """
    Determina la voz a utilizar con el orden de precedencia:
    1. topic['voice_name'] si existe y no está vacío.
    2. settings['voice_name'] si existe y no está vacío.
    3. Default: 'gemini:Charon-Informative'.
    """
    return (
        topic.get("voice_name")
        or settings.get("voice_name")
        or "gemini:Charon-Informative"
    )


def build_youtube_post(topic: dict) -> tuple[str, dict]:
    """
    Construye el título y metadatos para la publicación en YouTube Shorts.
    - Si el tema define 'youtube_title', se usa sin sufijo #Shorts y sin CTAs fijos en la descripción.
    - Si es tema legacy, mantiene '{subject[:80]} #Shorts' y el texto histórico de comentarios/suscripción.
    """
    script_text = topic["script"]
    tags = topic.get("tags", [])

    if topic.get("youtube_title"):
        title = topic["youtube_title"].strip()
        title = re.sub(r"\s*#shorts\b", "", title, flags=re.IGNORECASE).strip()
        tags_str = " ".join(f"#{t}" for t in tags)
        youtube_desc = f"{script_text}\n\n{tags_str}".strip()
    else:
        clean_subject = topic["subject"].strip()
        if "#shorts" not in clean_subject.lower():
            title = f"{clean_subject[:80]} #Shorts"
        else:
            title = clean_subject[:95]
        youtube_desc = (
            f"{script_text}\n\n¿Qué opinas? ¡Déjamelo saber en los comentarios y suscríbete para más curiosidades! 👇\n\n"
            + " ".join(f"#{t}" for t in tags)
        )

    youtube_extra = {
        "youtube_title": title,
        "youtube_description": youtube_desc,
        "tags": tags,
        "privacyStatus": "public",
        "containsSyntheticMedia": "true",
        "selfDeclaredMadeForKids": False,
    }
    return title, youtube_extra


def publish_topic_video(
    topic: dict, settings: dict, video_path: str | None = None
) -> dict:
    """
    Sube un video renderizado a las plataformas configuradas (YouTube Shorts).
    """
    target_video = video_path or topic.get("video_path")
    ups = UploadPostService()
    youtube_title, youtube_extra = build_youtube_post(topic)

    target_user = (
        topic.get("user_name")
        or settings.get("user_name")
        or settings.get("upload_post_username")
    )
    target_platforms = settings.get("platforms", ["youtube"])
    logger.info(
        f"Publicando [{topic.get('id')}] en {target_platforms} con usuario: {target_user}..."
    )

    return ups.upload_video(
        video_path=target_video,
        title=youtube_title,
        platforms=target_platforms,
        youtube_extra=youtube_extra,
        user_name=target_user,
    )


def publish_rendered_topic(topic_id: str) -> dict:
    """
    Publica un video previamente renderizado (en estado 'rendered') a YouTube.
    """
    data = load_topics_data()
    topic = next((t for t in data.get("topics", []) if t.get("id") == topic_id), None)
    if not topic:
        raise ValueError(f"Tema con id '{topic_id}' no encontrado en topics.json")

    video_path = topic.get("video_path")
    if not video_path or not os.path.isfile(video_path):
        task_id = topic.get("task_id", "")
        candidate = os.path.join(
            PROJECT_ROOT, "storage", "tasks", task_id, "final-1.mp4"
        )
        if os.path.isfile(candidate):
            video_path = candidate
            topic["video_path"] = candidate
        else:
            raise FileNotFoundError(
                f"Video final no encontrado para el tema {topic_id}: {video_path}"
            )

    settings = data.get("schedule_settings", {})
    try:
        upload_result = publish_topic_video(topic, settings)
        logger.info(f"Resultado de publicación para [{topic_id}]: {upload_result}")
    except Exception as e:
        logger.error(f"Error publicando [{topic_id}]: {e}")
        upload_result = {"success": False, "error": str(e)}

    if upload_result and upload_result.get("success"):
        topic["status"] = "published"
        topic["upload_result"] = upload_result
        topic["published_at"] = datetime.now().isoformat()
        save_topics_data(data)
        logger.info(f"Tema [{topic_id}] actualizado como 'published' en topics.json.")

    return {
        "success": bool(upload_result and upload_result.get("success")),
        "topic_id": topic_id,
        "video_path": video_path,
        "upload_result": upload_result,
    }


def prune_old_storage(max_cache_age_days: int = 2, max_task_age_days: int = 2) -> dict:
    """
    Limpia automáticamente el almacenamiento para evitar saturar el disco:
    1. Limpia clips huérfanos de cache_videos con más de max_cache_age_days días.
    2. En storage/tasks, elimina archivos pesados (.mp4, .wav, .mov) de tareas con más de max_task_age_days días,
       preservando script.json y subtítulos como registro histórico.
    """
    stats = {"cache_deleted": 0, "cache_bytes": 0, "task_deleted": 0, "task_bytes": 0}

    # 1. Limpieza de cache_videos
    try:
        from app.services.cache_manager import clean_video_cache

        res = clean_video_cache(max_age_days=max_cache_age_days)
        stats["cache_deleted"] = res.deleted_count
        stats["cache_bytes"] = res.deleted_size
        if res.deleted_count > 0:
            logger.info(
                f"Limpieza de caché: {res.deleted_count} clips eliminados ({res.deleted_size / (1024 * 1024):.2f} MB)."
            )
    except Exception as e:
        logger.warning(f"Error limpiando cache_videos: {e}")

    # 2. Limpieza de videos pesados en storage/tasks antiguos
    try:
        tasks_dir = os.path.join(PROJECT_ROOT, "storage", "tasks")
        cutoff_time = time.time() - (max_task_age_days * 86400)
        if os.path.isdir(tasks_dir):
            for task_folder in os.listdir(tasks_dir):
                task_path = os.path.join(tasks_dir, task_folder)
                if not os.path.isdir(task_path):
                    continue
                try:
                    folder_mtime = os.path.getmtime(task_path)
                    if folder_mtime < cutoff_time:
                        for f in os.listdir(task_path):
                            if f.endswith((".mp4", ".mov", ".avi", ".mkv", ".wav")):
                                f_path = os.path.join(task_path, f)
                                if os.path.isfile(f_path):
                                    f_size = os.path.getsize(f_path)
                                    os.unlink(f_path)
                                    stats["task_deleted"] += 1
                                    stats["task_bytes"] += f_size
                except Exception as ex_folder:
                    logger.debug(f"Saltando carpeta {task_folder}: {ex_folder}")
        if stats["task_deleted"] > 0:
            logger.info(
                f"Limpieza de tareas antiguas: {stats['task_deleted']} videos eliminados ({stats['task_bytes'] / (1024 * 1024):.2f} MB)."
            )
    except Exception as e:
        logger.warning(f"Error limpiando videos pesados de tasks: {e}")

    return stats


def run_production(auto_publish: bool = True, smart_check: bool = False) -> dict:
    logger.info("=== INICIANDO AUTO-PRODUCER MONEYPRINTERTURBO ===")

    # Mantenimiento preventivo de almacenamiento (< 2 días de retención)
    prune_old_storage(max_cache_age_days=2, max_task_age_days=2)

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

    if topic.get("experiment_variant"):
        today_str = datetime.now().strftime("%Y-%m-%d")
        already_published_today = any(
            t.get("experiment_variant")
            and (t.get("rendered_at") or "").startswith(today_str)
            for t in data.get("topics", [])
        )
        if already_published_today:
            msg = "Already published an experiment variant today"
            logger.info(f"{msg}. Skipping.")
            return {
                "success": True,
                "skipped": True,
                "reason": msg,
            }

    topic_id = topic["id"]
    subject = topic["subject"]

    # Validar esquema editorial antes de crear la tarea
    validate_topic_for_production(topic)
    script_text = prepare_script_text(topic)
    terms = topic.get("search_terms", [])

    logger.info(f"Produciendo tema: [{topic_id}] {subject}")

    # 1. Crear Tarea
    task = mpt_create_task(
        subject=subject, aspect=settings.get("aspect", "9:16"), language="es"
    )
    task_id = task["task_id"]
    logger.info(f"Tarea creada: {task_id}")

    # 2. Guardar Guion y Términos de Búsqueda
    mpt_update_script(task_id=task_id, script_text=script_text, terms=terms)
    logger.info("Guion y términos actualizados.")

    # 3. Síntesis de Voz con Fallback Inteligente (Gemini -> Edge-TTS)
    voice_name = resolve_topic_voice(topic, settings)
    voice_fallback = False
    try:
        voice_res = mpt_synthesize_voice(task_id=task_id, voice_name=voice_name)
        if not (isinstance(voice_res, dict) and voice_res.get("success")):
            raise RuntimeError(
                f"Voice synthesis returned unsuccessful result: {voice_res}"
            )
        logger.info(f"Voz sintetizada con {voice_name}: {voice_res}")
    except Exception as e:
        logger.warning(
            f"Fallo síntesis con {voice_name} ({e}). Aplicando fallback a Edge-TTS (es-ES-AlvaroNeural)..."
        )
        voice_name = "es-ES-AlvaroNeural"
        voice_fallback = True
        voice_res = mpt_synthesize_voice(task_id=task_id, voice_name=voice_name)
        logger.info(f"Voz sintetizada con fallback {voice_name}: {voice_res}")

    # Persistir inmediatamente la voz utilizada
    topic["voice_used"] = voice_name
    topic["voice_fallback"] = voice_fallback
    save_topics_data(data)

    # 4. Generación de Subtítulos Dinámicos Karaoke (Amarillo + Blanco + Borde Negro + Pop Spring)
    mpt_generate_subtitles(
        task_id=task_id,
        font_name=settings.get("font_name", "BeVietnamPro-Bold.ttf"),
        font_size=settings.get("font_size", 70),
        stroke_color=settings.get("stroke_color", "#000000"),
        stroke_width=settings.get("stroke_width", 6),
        text_color=settings.get("text_color", "#FFFFFF"),
        text_background_color="",
        rounded_subtitle_background=False,
        subtitle_position="bottom",
        custom_position=58.0,
        subtitle_animation="pop_spring",
    )
    # QA Check 1: Validar que el archivo de subtítulos (.srt) existe y no está vacío
    task_dir = os.path.join(utils.task_dir(), task_id)
    srt_file = os.path.join(task_dir, "subtitle.srt")
    if not os.path.isfile(srt_file) or os.path.getsize(srt_file) < 30:
        raise RuntimeError(
            f"QA GATE FAILED: El archivo de subtítulos {srt_file} no existe o está vacío. Abortando producción para evitar video sin subtítulos."
        )
    logger.info(
        f"QA GATE PASSED: Subtítulos verificados ({os.path.getsize(srt_file)} bytes)."
    )

    # 5. Descarga de Materiales 4K (Pexels)
    mat_res = mpt_fetch_materials(task_id=task_id, source="pexels")
    logger.info(f"Materiales descargados: {mat_res}")

    # 6. Renderizado con Smart Full-Screen Cover (Cero Barras Negras)
    clip_dur = settings.get("clip_duration", 2)
    render_res = mpt_render_video(
        task_id=task_id,
        bgm_name="random",
        bgm_volume=0.10,
        video_clip_duration=clip_dur,
        video_fit_mode="cover",
    )
    logger.info(f"Render final completado: {render_res}")

    video_path = render_res["videos"][0] if render_res.get("videos") else None
    if (
        not video_path
        or not os.path.isfile(video_path)
        or os.path.getsize(video_path) < 1_000_000
    ):
        raise RuntimeError(
            f"QA GATE FAILED: El video generado no existe o pesa menos de 1MB: {video_path}"
        )
    logger.info(
        f"QA GATE PASSED: Video final verificado ({os.path.getsize(video_path) / (1024 * 1024):.2f} MB)."
    )

    # 7. Publicación en YouTube
    upload_result = None
    if auto_publish:
        try:
            logger.info("Iniciando publicación en YouTube...")
            upload_result = publish_topic_video(topic, settings, video_path=video_path)
            logger.info(
                f"Resultado de publicación en {settings.get('platforms', ['youtube'])}: {upload_result}"
            )
        except Exception as e:
            logger.error(
                f"Error publicando en {settings.get('platforms', ['youtube'])}: {e}"
            )
            upload_result = {"success": False, "error": str(e)}

    # 8. Actualizar topics.json
    now_str = datetime.now().isoformat()
    topic["status"] = (
        "published" if upload_result and upload_result.get("success") else "rendered"
    )
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
        "upload_result": upload_result,
        "voice_used": voice_name,
        "voice_fallback": voice_fallback,
    }


if __name__ == "__main__":
    if "--publish-rendered" in sys.argv:
        idx = sys.argv.index("--publish-rendered")
        target_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "topic_067"
        res = publish_rendered_topic(target_id)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        sys.exit(0 if res.get("success") else 1)

    auto_pub = "--no-publish" not in sys.argv
    smart_mode = "--smart" in sys.argv
    result = run_production(auto_publish=auto_pub, smart_check=smart_mode)
    print(json.dumps(result, indent=2, ensure_ascii=False))
