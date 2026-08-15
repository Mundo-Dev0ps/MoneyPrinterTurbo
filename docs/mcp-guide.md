# Guía de Integración: Servidor MCP para MoneyPrinterTurbo

MoneyPrinterTurbo incluye un **servidor nativo de Model Context Protocol (MCP)** basado en el SDK oficial `FastMCP`. Esto permite que agentes de Inteligencia Artificial (como Antigravity, Claude Desktop, Cursor, Cline, etc.) interactúen con el motor de generación y edición de videos en lenguaje natural.

---

## 1. Modos de Ejecución del Servidor MCP

El servidor puede ejecutarse de dos maneras: **dentro de un contenedor Docker** (recomendado para no sobrecargar el sistema anfitrión con dependencias pesadas) o **localmente con `uv`**.

### Opción A: En Contenedor Docker (Recomendada)

#### 1. Modo Efímero (stdio)
El agente de IA lanza el contenedor Docker automáticamente al interactuar:

**En `claude_desktop_config.json` o configuración de Antigravity / Cursor:**
```json
{
  "mcpServers": {
    "moneyprinterturbo": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-v", "/home/mundo-devops/mundo-devops/repos/MoneyPrinterTurbo/config.toml:/app/config.toml",
        "-v", "/home/mundo-devops/mundo-devops/repos/MoneyPrinterTurbo/storage:/app/storage",
        "-v", "/home/mundo-devops/mundo-devops/repos/MoneyPrinterTurbo/resource:/app/resource",
        "ghcr.io/harry0703/moneyprinterturbo:latest",
        "python", "mcp_server.py"
      ]
    }
  }
}
```

#### 2. Modo Servicio con Docker Compose (SSE en puerto 8000)
Agrega el servicio `mcp` a tu `docker-compose.yml`:
```yaml
  mcp:
    image: ghcr.io/harry0703/moneyprinterturbo:latest
    container_name: mpt-mcp
    restart: unless-stopped
    command: python mcp_server.py --transport sse --port 8000
    ports:
      - "8000:8000"
    volumes:
      - ./config.toml:/app/config.toml
      - ./storage:/app/storage
      - ./resource:/app/resource
```
Luego en tu cliente MCP configuras la URL SSE:
`http://localhost:8000/sse`

---

### Opción B: Ejecución Local con `uv`

Si prefieres correrlo directamente en local:
```bash
uv run python mcp_server.py
```

**Configuración en `claude_desktop_config.json`:**
```json
{
  "mcpServers": {
    "moneyprinterturbo": {
      "command": "uv",
      "args": [
        "run",
        "--python",
        "3.11",
        "python",
        "/home/mundo-devops/mundo-devops/repos/MoneyPrinterTurbo/mcp_server.py"
      ]
    }
  }
}
```

---

## 2. Catálogo de Herramientas MCP (*Tools*)

### 🛠️ Configuración y Estado del Sistema
* `mpt_get_status()`: Consulta el estado del sistema, disponibilidad de FFmpeg y proveedores configurados (sin exponer credenciales).
* `mpt_update_settings(key, value)`: Actualiza parámetros y claves de forma segura en `config.toml`.
* `mpt_list_voices(language)`: Lista las voces TTS disponibles filtradas por código de idioma (ej. `es`, `en`, `zh`).
* `mpt_list_fonts()`: Lista las fuentes tipográficas disponibles en `resource/fonts`.
* `mpt_list_bgm()`: Lista las canciones de fondo disponibles en `resource/songs`.

### 🚀 Modo One-Shot (Generación Completa en 1 Paso)
* `mpt_generate_full_video(subject, aspect, voice_name, language, video_source, font_name, bgm_volume, ...)`: Ejecuta el flujo completo automático y retorna las rutas de los videos MP4 generados.

### 🎨 Modo Granular (Edición Iterativa Paso a Paso)
* `mpt_create_task(subject, aspect, language)`: Inicializa una tarea y su directorio en `storage/tasks/<task_id>/`.
* `mpt_generate_script(task_id, subject, prompt_hint)`: Redacta el guion y los términos de búsqueda con el LLM.
* `mpt_update_script(task_id, script_text, terms)`: Modifica directamente el guion o las palabras clave.
* `mpt_synthesize_voice(task_id, voice_name, voice_rate, voice_volume)`: Genera el archivo de locución de audio (`audio.mp3`) y calcula su duración.
* `mpt_generate_subtitles(task_id, font_name, text_color, font_size, subtitle_position)`: Genera `subtitle.srt` y configura el estilo visual de subtítulos.
* `mpt_fetch_materials(task_id, source)`: Descarga clips de video HD coincidentes desde Pexels o Pixabay.
* `mpt_inspect_materials(task_id)`: Muestra el desglose de escenas con los videos y términos asignados.
* `mpt_replace_scene_material(task_id, scene_index, search_query_or_file)`: Sustituye el video de una escena por otro término de búsqueda o por un archivo local.
* `mpt_render_video(task_id, bgm_name, bgm_volume, video_concat_mode, ...)`: Ensambla el video final.
* `mpt_get_task_progress(task_id)`: Monitorea el progreso y estado de la tarea.

---

## 3. Catálogo de Recursos MCP (*Resources*)

* `mpt://tasks/{task_id}/script`: Contenido estructurado de `script.json`.
* `mpt://tasks/{task_id}/subtitles`: Contenido del archivo de subtítulos `subtitle.srt`.
* `mpt://tasks/{task_id}/summary`: Resumen de artefactos generados (audio, video, subtítulos, clips).

---

## 4. Ejemplos de Interacción en Lenguaje Natural

### Ejemplo 1: Creación Directa (One-Shot)
> **Usuario:** *"Crea un video vertical en español sobre la historia del telescopio espacial James Webb."*  
> **Agente:** Ejecuta `mpt_generate_full_video(subject="Historia del telescopio espacial James Webb", aspect="9:16", language="es")` y entrega el video final MP4.

### Ejemplo 2: Creación Paso a Paso con Modificaciones
> **Paso 1 (Guion):** *"Borrador de video sobre los beneficios del té matcha."* $\rightarrow$ Llama `mpt_create_task` + `mpt_generate_script`.  
> **Paso 2 (Ajuste):** *"Cambia el final del guion para invitar a comentar."* $\rightarrow$ Llama `mpt_update_script`.  
> **Paso 3 (Locución):** *"Usa una voz en español neutro."* $\rightarrow$ Llama `mpt_synthesize_voice(voice_name="es-MX-DaliaNeural-Female")`.  
> **Paso 4 (Materiales):** *"Descarga los clips y muéstramelos."* $\rightarrow$ Llama `mpt_fetch_materials` + `mpt_inspect_materials`.  
> **Paso 5 (Reemplazo de escena):** *"El segundo clip de la taza no me gusta, busca uno de una plantación de té."* $\rightarrow$ Llama `mpt_replace_scene_material(scene_index=1, search_query_or_file="green tea plantation")`.  
> **Paso 6 (Montaje final):** *"Renderiza el video con música suave y subtítulos amarillos."* $\rightarrow$ Llama `mpt_render_video(bgm_volume=0.15)` y entrega el archivo final.
