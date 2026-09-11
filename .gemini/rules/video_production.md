# Reglas de Producción de Video de MoneyPrinterTurbo (ErDivertido / Mundo-DevOps)

Este documento define las reglas de calidad obligatorias para la generación de videos verticales (Shorts, Reels, TikTok) con MoneyPrinterTurbo y Antigravity.

---

## 1. Reglas de Términos de Búsqueda y Clips (Pexels / Stock)
* **Prohibido usar palabras ambiguas de conflicto:** NUNCA usar `war`, `military`, `weapons`, `destruction`, `rubble`, `ruins` o `bomb` porque traen clips bélicos o irrelevantes.
* **Términos de alta precisión:** Usar siempre términos documentales, científicos y geológicos específicos en inglés (ejemplo para terremotos: `seismograph monitor needle`, `ground crack geology`, `tectonic plates 3d earth`, `fault line fissure`, `tsunami sea waves`).
* **Duración máxima por clip:** **2 segundos** (`video_clip_duration = 2`) para mantener un ritmo dinámico de corte rápido (~15 cortes por cada 30 segundos).

---

## 2. Reglas de Subtítulos Premium
* **Tipografía:** `BeVietnamPro-Bold.ttf`
* **Tamaño:** `70` a `75px`
* **Color de texto:** Blanco puro `#FFFFFF` o Amarillo `#FFFF00`
* **Contorno / Trazo:** Negro `#000000` con `stroke_width = 2.5`
* **Fondo redondeado (*Pill Badge*):** `rounded_subtitle_background = True` con `text_background_color = "#000000"` semi-transparente
* **Posición:** `bottom` (con `custom_position = 70.0` a `72.0`)

---

## 3. Reglas de Publicación (Upload-Post / YouTube)
* **Perfil por defecto:** `ErDivertido`
* **Declaración de IA:** `containsSyntheticMedia = "true"` para cumplir con normativas de YouTube
* **Formato de título:** Gancho de menos de 100 caracteres con `#Shorts` al final
* **Descripción:** 2 párrafos explicativos + llamada a la acción en comentarios + 5-7 hashtags relevantes

---

## 4. Regla Obligatoria de Ejecución en Contenedores Docker
* **Principio:** Todos los comandos de ejecución (pruebas con `pytest`, scripts de producción `auto_producer.py`, comandos CLI y Python) **DEBEN ejecutarse siempre DENTRO de los contenedores Docker**, NUNCA directamente en el host.
* **Patrón de Ejecución Local de Pruebas:**
  ```bash
  docker run --rm \
    -v /home/mundo-devops/mundo-devops/repos/MoneyPrinterTurbo:/MoneyPrinterTurbo \
    -w /MoneyPrinterTurbo \
    ghcr.io/harry0703/moneyprinterturbo:latest \
    sh -c "pip install -q pytest 'mcp>=1.3.0,<2' >/dev/null 2>&1 && pytest <ruta_test> -v"
  ```
* **Patrón de Ejecución en Contenedores Vivos:**
  ```bash
  docker exec <container_id_or_name> python3 <script>
  ```
* **Patrón en VPS:** Se utiliza siempre el wrapper `scripts/run_remote_producer.sh`.

