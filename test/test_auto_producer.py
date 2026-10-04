import json
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from scripts import auto_producer


class TestAutoProducer(unittest.TestCase):
    def test_imports_and_symbols(self):
        """Verifica que todos los módulos y funciones requeridos por auto_producer existen."""
        self.assertTrue(hasattr(auto_producer, "run_production"))
        self.assertTrue(hasattr(auto_producer, "publish_rendered_topic"))
        self.assertTrue(hasattr(auto_producer, "publish_topic_video"))
        self.assertTrue(hasattr(auto_producer, "load_topics_data"))
        self.assertTrue(hasattr(auto_producer, "save_topics_data"))
        self.assertTrue(hasattr(auto_producer, "UploadPostService"))
        self.assertTrue(hasattr(auto_producer, "mpt_create_task"))
        self.assertTrue(hasattr(auto_producer, "mpt_update_script"))
        self.assertTrue(hasattr(auto_producer, "mpt_synthesize_voice"))
        self.assertTrue(hasattr(auto_producer, "mpt_generate_subtitles"))
        self.assertTrue(hasattr(auto_producer, "mpt_fetch_materials"))
        self.assertTrue(hasattr(auto_producer, "mpt_render_video"))
        self.assertTrue(hasattr(auto_producer, "prune_old_storage"))

    @patch("scripts.auto_producer.prune_old_storage")
    @patch("scripts.auto_producer.refill_topics_if_needed")
    @patch("scripts.auto_producer.UploadPostService")
    @patch("scripts.auto_producer.mpt_render_video")
    @patch("scripts.auto_producer.mpt_fetch_materials")
    @patch("scripts.auto_producer.mpt_generate_subtitles")
    @patch("scripts.auto_producer.mpt_synthesize_voice")
    @patch("scripts.auto_producer.mpt_update_script")
    @patch("scripts.auto_producer.mpt_create_task")
    @patch("scripts.auto_producer.load_topics_data")
    @patch("scripts.auto_producer.save_topics_data")
    @patch("os.path.isfile")
    @patch("os.path.getsize")
    def test_full_production_and_upload_success(
        self,
        mock_getsize,
        mock_isfile,
        mock_save_topics,
        mock_load_topics,
        mock_create_task,
        mock_update_script,
        mock_synth_voice,
        mock_gen_subtitles,
        mock_fetch_mat,
        mock_render_vid,
        mock_upload_post_cls,
        mock_refill,
        mock_prune,
    ):
        """Valida que run_production ejecuta el flujo completo e instancia y llama a UploadPostService correctamente."""
        mock_data = {
            "schedule_settings": {
                "platforms": ["youtube", "instagram"],
                "user_name": "ErDivertido",
            },
            "topics": [
                {
                    "id": "test_topic_001",
                    "subject": "¿Es posible viajar en el tiempo? 😱",
                    "script": "Texto de prueba para el video.",
                    "status": "pending",
                    "tags": ["ciencia", "espacio"],
                    "search_terms": ["time travel space stars"],
                }
            ],
        }
        mock_load_topics.return_value = mock_data
        mock_create_task.return_value = {"task_id": "test-task-1234"}
        mock_update_script.return_value = {"success": True}
        mock_synth_voice.return_value = {
            "success": True,
            "audio_file": "audio.mp3",
            "audio_duration": 30,
        }
        mock_gen_subtitles.return_value = {"success": True}
        mock_fetch_mat.return_value = {"success": True, "downloaded_count": 5}
        mock_render_vid.return_value = {
            "success": True,
            "videos": ["storage/tasks/test-task-1234/final-1.mp4"],
            "combined_videos": ["storage/tasks/test-task-1234/combined-1.mp4"],
            "warnings": [],
        }

        # Setup mock file checks for QA gates
        mock_isfile.return_value = True
        mock_getsize.side_effect = lambda f: 100 if "subtitle.srt" in f else 10_000_000

        # Setup mock UploadPostService instance
        mock_ups_instance = MagicMock()
        mock_ups_instance.upload_video.return_value = {
            "success": True,
            "request_id": "req-123",
            "job_id": "job-456",
        }
        mock_upload_post_cls.return_value = mock_ups_instance

        # Run production
        result = auto_producer.run_production(auto_publish=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["topic_id"], "test_topic_001")
        self.assertTrue(result["upload_result"]["success"])

        # Verify UploadPostService was instantiated and upload_video called
        mock_upload_post_cls.assert_called_once()
        mock_ups_instance.upload_video.assert_called_once()
        call_kwargs = mock_ups_instance.upload_video.call_args.kwargs
        self.assertEqual(call_kwargs["platforms"], ["youtube", "instagram"])
        self.assertEqual(call_kwargs["user_name"], "ErDivertido")
        self.assertIn("#Shorts", call_kwargs["title"])

    @patch("scripts.auto_producer.refill_topics_if_needed")
    @patch("scripts.auto_producer.save_topics_data")
    @patch("scripts.auto_producer.mpt_create_task")
    @patch("scripts.auto_producer.mpt_synthesize_voice")
    @patch("scripts.auto_producer.mpt_generate_subtitles")
    @patch("scripts.auto_producer.load_topics_data")
    @patch("os.path.isfile")
    @patch("os.path.getsize")
    def test_qa_gate_fails_if_subtitles_missing(
        self,
        mock_getsize,
        mock_isfile,
        mock_load_topics,
        mock_gen_subtitles,
        mock_synth_voice,
        mock_create_task,
        mock_save_topics,
        mock_refill,
    ):
        """Valida que el QA Gate 1 aborta la producción si subtitle.srt no existe o está vacío."""
        mock_data = {
            "schedule_settings": {},
            "topics": [
                {
                    "id": "test_topic_002",
                    "subject": "Tema sin subtitulos",
                    "script": "Texto de prueba.",
                    "status": "pending",
                }
            ],
        }
        mock_load_topics.return_value = mock_data
        mock_create_task.return_value = {"task_id": "test-task-sub-fail"}
        mock_synth_voice.return_value = {
            "success": True,
            "audio_file": "audio.mp3",
            "audio_duration": 30,
        }
        mock_gen_subtitles.return_value = {"success": True}

        # Mock missing subtitle file
        mock_isfile.return_value = False

        with self.assertRaises(RuntimeError) as ctx:
            auto_producer.run_production(auto_publish=True)
        self.assertIn("QA GATE FAILED", str(ctx.exception))

    @patch("scripts.auto_producer.prune_old_storage")
    @patch("scripts.auto_producer.refill_topics_if_needed")
    @patch("scripts.auto_producer.UploadPostService")
    @patch("scripts.auto_producer.mpt_render_video")
    @patch("scripts.auto_producer.mpt_fetch_materials")
    @patch("scripts.auto_producer.mpt_generate_subtitles")
    @patch("scripts.auto_producer.mpt_synthesize_voice")
    @patch("scripts.auto_producer.mpt_update_script")
    @patch("scripts.auto_producer.mpt_create_task")
    @patch("scripts.auto_producer.load_topics_data")
    @patch("scripts.auto_producer.save_topics_data")
    @patch("os.path.isfile")
    @patch("os.path.getsize")
    def test_qa_gate_fails_if_video_too_small(
        self,
        mock_getsize,
        mock_isfile,
        mock_save_topics,
        mock_load_topics,
        mock_create_task,
        mock_update_script,
        mock_synth_voice,
        mock_gen_subtitles,
        mock_fetch_mat,
        mock_render_vid,
        mock_upload_post_cls,
        mock_refill,
        mock_prune,
    ):
        """Valida que el QA Gate 2 aborta la producción si final-1.mp4 pesa menos de 1 MB."""
        mock_data = {
            "schedule_settings": {},
            "topics": [
                {
                    "id": "test_topic_003",
                    "subject": "Tema video corrupto",
                    "script": "Texto de prueba.",
                    "status": "pending",
                }
            ],
        }
        mock_load_topics.return_value = mock_data
        mock_create_task.return_value = {"task_id": "test-task-corrupt"}
        mock_update_script.return_value = {"success": True}
        mock_synth_voice.return_value = {
            "success": True,
            "audio_file": "audio.mp3",
            "audio_duration": 30,
        }
        mock_gen_subtitles.return_value = {"success": True}
        mock_fetch_mat.return_value = {"success": True, "downloaded_count": 5}
        mock_render_vid.return_value = {
            "success": True,
            "videos": ["storage/tasks/test-task-corrupt/final-1.mp4"],
            "warnings": [],
        }

        mock_isfile.return_value = True
        # Subtitle is good (500 bytes), but video file is only 500 bytes (corrupt/empty)
        mock_getsize.side_effect = lambda f: 500 if "subtitle.srt" in f else 500

        with self.assertRaises(RuntimeError) as ctx:
            auto_producer.run_production(auto_publish=True)
        self.assertIn("QA GATE FAILED", str(ctx.exception))

    @patch("scripts.auto_producer.UploadPostService")
    @patch("scripts.auto_producer.load_topics_data")
    @patch("scripts.auto_producer.save_topics_data")
    @patch("os.path.isfile")
    def test_publish_rendered_topic_success(
        self,
        mock_isfile,
        mock_save_topics,
        mock_load_topics,
        mock_upload_post_cls,
    ):
        """Valida que publish_rendered_topic publica un video en estado rendered."""
        mock_data = {
            "schedule_settings": {"platforms": ["youtube"], "user_name": "ErDivertido"},
            "topics": [
                {
                    "id": "topic_067",
                    "subject": "El Megaterremoto de Valdivia 1960",
                    "script": "Texto de Valdivia.",
                    "status": "rendered",
                    "task_id": "valdivia-task-id",
                    "video_path": "/storage/tasks/valdivia-task-id/final-1.mp4",
                    "tags": ["valdivia", "chile"],
                }
            ],
        }
        mock_load_topics.return_value = mock_data
        mock_isfile.return_value = True

        mock_ups_instance = MagicMock()
        mock_ups_instance.upload_video.return_value = {
            "success": True,
            "request_id": "req-valdivia",
            "job_id": "job-valdivia",
        }
        mock_upload_post_cls.return_value = mock_ups_instance

        res = auto_producer.publish_rendered_topic("topic_067")
        self.assertTrue(res["success"])
        self.assertEqual(res["topic_id"], "topic_067")
        self.assertEqual(mock_data["topics"][0]["status"], "published")
        mock_ups_instance.upload_video.assert_called_once()
        call_kwargs = mock_ups_instance.upload_video.call_args.kwargs
        self.assertEqual(call_kwargs["user_name"], "ErDivertido")
        self.assertEqual(call_kwargs["platforms"], ["youtube"])
        self.assertEqual(call_kwargs["youtube_extra"]["selfDeclaredMadeForKids"], False)

    @patch("app.services.cache_manager.clean_video_cache")
    @patch("os.path.isdir")
    @patch("os.listdir")
    def test_prune_old_storage(self, mock_listdir, mock_isdir, mock_clean_cache):
        """Valida que prune_old_storage invoca clean_video_cache y limpia tareas viejas."""
        from app.services.cache_manager import VideoCacheCleanupResult

        mock_clean_cache.return_value = VideoCacheCleanupResult(
            deleted_count=5, deleted_size=50000000
        )
        mock_isdir.return_value = False

        stats = auto_producer.prune_old_storage(
            max_cache_age_days=2, max_task_age_days=2
        )
        mock_clean_cache.assert_called_once_with(max_age_days=2)
        self.assertEqual(stats["cache_deleted"], 5)
        self.assertEqual(stats["cache_bytes"], 50000000)

    @patch("app.services.llm.generate_response")
    @patch("scripts.auto_producer.save_topics_data")
    def test_refill_topics_if_needed(self, mock_save, mock_llm_gen):
        """Verifica que refill_topics_if_needed genera y filtra temas sin errores de imports."""
        mock_data = {
            "schedule_settings": {},
            "topics": [
                {
                    "id": "topic_001",
                    "subject": "El Megaterremoto de Valdivia 1960",
                    "status": "published",
                }
            ],
        }
        mock_llm_gen.return_value = json.dumps(
            [
                {
                    "subject": "El Megaterremoto de Valdivia 1960",
                    "category": "Sismos",
                    "script": "Texto repetido",
                    "search_terms": ["valdivia earthquake"],
                    "tags": ["shorts"],
                },
                {
                    "editorial_version": "retention-v1",
                    "youtube_title": "La fosa que congela a las criaturas marinas",
                    "subject": "La Fosa de las Sandwich del Sur Inédita",
                    "category": "Abismo",
                    "script": "En el extremo sur existe un abismo helado. [pause:0.4] La fosa de las Sandwich del Sur desciende a más de ocho mil metros de profundidad bajo aguas antárticas. Allí la presión aplasta casi todo mientras extrañas criaturas sobreviven adaptadas a temperaturas cercanas al punto de congelación constante.",
                    "search_terms": [
                        "South Sandwich trench Antarctica ocean",
                        "antarctic abyss underwater deep sea",
                        "extreme cold deep marine creatures",
                        "submersible diving freezing ocean depth",
                        "hydrothermal freezing abyss ocean floor",
                    ],
                    "tags": ["shorts"],
                },
            ]
        )
        added = auto_producer.refill_topics_if_needed(
            mock_data, min_pending=2, batch_size=2
        )
        self.assertEqual(added, 1)
        self.assertEqual(len(mock_data["topics"]), 2)
        self.assertEqual(mock_data["topics"][-1]["id"], "topic_002")
        self.assertEqual(
            mock_data["topics"][-1]["subject"],
            "La Fosa de las Sandwich del Sur Inédita",
        )

    def test_validate_retention_topic_accepts_complete_topic(self):
        """Valida que un tema retention-v1 perfectamente configurado pasa la validación sin errores."""
        valid_topic = {
            "editorial_version": "retention-v1",
            "youtube_title": "Apofis pasará dentro de la órbita satelital",
            "subject": "Apophis 2029: El asteroide que rozará la Tierra",
            "script": "Apofis pasará más cerca que muchos satélites. [pause:0.4] El 13 de abril de 2029, este asteroide de unos 340 metros cruzará a solo 32.000 kilómetros de la superficie terrestre. No chocará con nosotros: la gravedad de la Tierra alterará su órbita y podría sacudir su superficie.",
            "search_terms": [
                "Apophis asteroid space animation Earth",
                "geostationary satellites orbiting planet Earth",
                "large rocky asteroid close up",
                "asteroid passing near blue Earth",
                "spacecraft observing asteroid rocky surface",
            ],
            "tags": ["shorts", "ciencia", "misterios"],
            "experiment_variant": "A",
            "voice_name": "gemini:Charon-Informative",
        }
        auto_producer.validate_topic_for_production(valid_topic)

    def test_validate_retention_topic_reports_each_invalid_field(self):
        """Valida que validate_topic_for_production detecta y rechaza cada regla editorial con el campo infractor."""
        base_valid = {
            "editorial_version": "retention-v1",
            "youtube_title": "Apofis pasará dentro de la órbita satelital",
            "subject": "Apophis 2029",
            "script": "Apofis pasará más cerca que muchos satélites. [pause:0.4] El 13 de abril de 2029, este asteroide de unos 340 metros cruzará a solo 32.000 kilómetros de la superficie terrestre. No chocará con nosotros: la gravedad de la Tierra alterará su órbita y podría sacudir su superficie.",
            "search_terms": [
                "Apophis asteroid space animation Earth",
                "geostationary satellites orbiting planet Earth",
                "large rocky asteroid close up",
                "asteroid passing near blue Earth",
                "spacecraft observing asteroid rocky surface",
            ],
            "tags": ["shorts"],
        }

        cases = [
            (
                "short_title",
                {"youtube_title": "Asteroide Apofis cerca"},
                "youtube_title",
            ),
            (
                "long_title",
                {
                    "youtube_title": "Este es un título excesivamente largo para YouTube Shorts que pasa cincuenta y cinco"
                },
                "youtube_title",
            ),
            (
                "title_with_shorts",
                {"youtube_title": "Apofis pasará dentro de la órbita #Shorts"},
                "youtube_title",
            ),
            (
                "title_with_colon",
                {"youtube_title": "Apofis: El asteroide que rozará la Tierra hoy"},
                "youtube_title",
            ),
            (
                "short_script",
                {
                    "script": "Apofis pasará más cerca que satélites. [pause:0.4] Este asteroide cruzará cerca de la Tierra pero no chocará."
                },
                "guion",
            ),
            (
                "long_script",
                {
                    "script": "Apofis pasará más cerca que muchos satélites. [pause:0.4] El trece de abril del año dos mil veintinueve este colosal asteroide de más de trescientos cuarenta metros de diámetro cruzará a una distancia de solo treinta y dos mil kilómetros de nuestra superficie terrestre sin impactar directamente contra nuestro planeta aunque alterará su órbita para siempre debido a la gravedad de la Tierra y sus intensas mareas gravitacionales."
                },
                "guion",
            ),
            (
                "long_hook",
                {
                    "script": "Un gigantesco asteroide de trescientos metros pasará cerca de la Tierra. [pause:0.4] El 13 de abril de 2029, la roca cruzará a solo 32.000 kilómetros de la superficie terrestre. No chocará con nosotros: la gravedad de la Tierra alterará su órbita y podría sacudir su superficie."
                },
                "gancho",
            ),
            (
                "forbidden_intro",
                {
                    "script": "En el corazón de nuestro sistema solar viaja Apofis. [pause:0.4] El trece de abril del año 2029, este colosal asteroide de unos 340 metros cruzará a una distancia de solo 32.000 kilómetros de la superficie terrestre. No chocará con nosotros: la gravedad de la Tierra alterará su órbita y podría sacudir su superficie."
                },
                "guion",
            ),
            (
                "cta_comentarios",
                {
                    "script": "Apofis pasará más cerca que muchos satélites. [pause:0.4] El trece de abril del año 2029, este colosal asteroide de unos 340 metros cruzará a una distancia de solo 32.000 kilómetros de la superficie terrestre. No chocará con nosotros. ¿Qué opinas? ¡Déjamelo saber en los comentarios!"
                },
                "guion",
            ),
            (
                "cta_suscribete",
                {
                    "script": "Apofis pasará más cerca que muchos satélites. [pause:0.4] El trece de abril del año 2029, este colosal asteroide de unos 340 metros cruzará a solo 32.000 kilómetros de la superficie terrestre. No chocará con nosotros: la gravedad alterará su órbita para siempre. Suscríbete para más curiosidades del espacio."
                },
                "guion",
            ),
            (
                "wrong_pause_duration",
                {
                    "script": "Apofis pasará más cerca que muchos satélites. [pause:0.6] El 13 de abril de 2029, este asteroide de unos 340 metros cruzará a solo 32.000 kilómetros de la superficie terrestre. No chocará con nosotros: la gravedad de la Tierra alterará su órbita y podría sacudir su superficie."
                },
                "pausa",
            ),
            (
                "multiple_pauses",
                {
                    "script": "Apofis pasará más cerca que muchos satélites. [pause:0.4] El trece de abril de 2029, este asteroide de unos 340 metros cruzará a solo 32.000 kilómetros de la Tierra. [pause:0.4] No chocará con nosotros: la gravedad de nuestro planeta alterará su órbita y podría sacudir su superficie rocosa."
                },
                "pausa",
            ),
            (
                "pause_not_after_hook",
                {
                    "script": "Apofis pasará más cerca que muchos satélites. El trece de abril de 2029 [pause:0.4], este asteroide de unos 340 metros cruzará a solo 32.000 kilómetros de la superficie terrestre. No chocará con nosotros: la gravedad de la Tierra alterará su órbita y podría sacudir su superficie."
                },
                "pausa",
            ),
            (
                "four_terms",
                {
                    "search_terms": [
                        "one two three four",
                        "two three four five",
                        "three four five six",
                        "four five six seven",
                    ]
                },
                "search_terms",
            ),
            (
                "short_term",
                {
                    "search_terms": [
                        "asteroid space Earth",
                        "geostationary satellites orbiting planet Earth",
                        "large rocky asteroid close up",
                        "asteroid passing near blue Earth",
                        "spacecraft observing asteroid rocky surface",
                    ]
                },
                "search_terms",
            ),
            (
                "long_term",
                {
                    "search_terms": [
                        "this is an excessively long search term with nine words total",
                        "geostationary satellites orbiting planet Earth",
                        "large rocky asteroid close up",
                        "asteroid passing near blue Earth",
                        "spacecraft observing asteroid rocky surface",
                    ]
                },
                "search_terms",
            ),
            (
                "duplicate_terms",
                {
                    "search_terms": [
                        "geostationary satellites orbiting planet Earth",
                        "geostationary satellites orbiting planet Earth",
                        "large rocky asteroid close up",
                        "asteroid passing near blue Earth",
                        "spacecraft observing asteroid rocky surface",
                    ]
                },
                "search_terms",
            ),
        ]

        for case_name, override, expected_field_keyword in cases:
            with self.subTest(case=case_name):
                bad_topic = {**base_valid, **override}
                with self.assertRaises(ValueError) as ctx:
                    auto_producer.validate_topic_for_production(bad_topic)
                self.assertIn(
                    expected_field_keyword.lower(), str(ctx.exception).lower()
                )

    def test_prepare_script_text_preserves_retention_pause(self):
        """Un tema retention-v1 conserva exactamente su pausa [pause:0.4] sin alteración."""
        topic = {
            "editorial_version": "retention-v1",
            "script": "Apofis pasará más cerca que muchos satélites. [pause:0.4] El 13 de abril de 2029, este asteroide cruzará a 32.000 kilómetros.",
        }
        prepared = auto_producer.prepare_script_text(topic)
        self.assertEqual(prepared, topic["script"])

    def test_prepare_script_text_keeps_legacy_pause_behavior(self):
        """Un tema histórico sin editorial_version recibe la pausa [pause:0.6] heredada."""
        legacy_topic = {
            "script": "Texto histórico sin pausa previa. Segunda frase del guion."
        }
        prepared = auto_producer.prepare_script_text(legacy_topic)
        self.assertIn("[pause:0.6]", prepared)

    def test_validate_topic_for_production_accepts_legacy_topic(self):
        """Temas históricos sin editorial_version no fallan validación editorial."""
        legacy_topic = {
            "subject": "Legacy Title",
            "script": "Texto histórico de 10 palabras.",
        }
        # No levanta excepción
        auto_producer.validate_topic_for_production(legacy_topic)

    @patch("app.services.llm.generate_response")
    @patch("scripts.auto_producer.save_topics_data")
    def test_refill_topics_keeps_only_valid_retention_items(
        self, mock_save, mock_llm_gen
    ):
        """Refill conserva únicamente los temas que cumplen el contrato retention-v1 y descarta los inválidos."""
        mock_data = {
            "schedule_settings": {},
            "topics": [
                {"id": "topic_001", "subject": "Tema Existente", "status": "published"}
            ],
        }
        valid_item = {
            "editorial_version": "retention-v1",
            "youtube_title": "Apofis pasará dentro de la órbita satelital",
            "subject": "Apophis 2029",
            "category": "Cosmos",
            "script": "Apofis pasará más cerca que muchos satélites. [pause:0.4] El 13 de abril de 2029, este asteroide de unos 340 metros cruzará a solo 32.000 kilómetros de la superficie terrestre. No chocará con nosotros: la gravedad de la Tierra alterará su órbita y podría sacudir su superficie.",
            "search_terms": [
                "Apophis asteroid space animation Earth",
                "geostationary satellites orbiting planet Earth",
                "large rocky asteroid close up",
                "asteroid passing near blue Earth",
                "spacecraft observing asteroid rocky surface",
            ],
            "tags": ["shorts"],
        }
        invalid_item = {
            "editorial_version": "retention-v1",
            "youtube_title": "Corto",  # Inválido: < 35 caracteres
            "subject": "Tema Invalido",
            "script": "Texto muy corto.",
            "search_terms": ["term"],
            "tags": ["shorts"],
        }

        mock_llm_gen.return_value = json.dumps([valid_item, invalid_item])
        added = auto_producer.refill_topics_if_needed(
            mock_data, min_pending=2, batch_size=2
        )

        self.assertEqual(added, 1)
        self.assertEqual(len(mock_data["topics"]), 2)
        added_topic = mock_data["topics"][-1]
        self.assertEqual(added_topic["editorial_version"], "retention-v1")
        self.assertEqual(added_topic["youtube_title"], valid_item["youtube_title"])

        # Verificar que el prompt solicita retention-v1 y requisitos editoriales
        call_prompt = mock_llm_gen.call_args.kwargs.get("prompt", "")
        self.assertIn("retention-v1", call_prompt)
        self.assertIn("[pause:0.4]", call_prompt)
        self.assertIn("45", call_prompt)

    def test_build_youtube_post_uses_custom_title_without_shorts_suffix(self):
        topic = {
            "youtube_title": "Apofis pasará dentro de la órbita satelital",
            "script": "Texto del guion experimental.",
            "tags": ["shorts", "ciencia"],
        }
        title, extra = auto_producer.build_youtube_post(topic)
        self.assertEqual(title, "Apofis pasará dentro de la órbita satelital")
        self.assertNotIn("#Shorts", title)
        self.assertNotIn("suscríbete", extra["youtube_description"].lower())
        self.assertNotIn("déjamelo saber", extra["youtube_description"].lower())
        self.assertIn("#shorts", extra["youtube_description"])
        self.assertEqual(extra["selfDeclaredMadeForKids"], False)

    def test_build_youtube_post_preserves_legacy_subject_fallback(self):
        legacy_topic = {
            "subject": "El Megaterremoto de Valdivia 1960",
            "script": "Texto histórico de Valdivia.",
            "tags": ["valdivia", "chile"],
        }
        title, extra = auto_producer.build_youtube_post(legacy_topic)
        self.assertTrue(title.endswith("#Shorts"))
        self.assertIn("¿Qué opinas?", extra["youtube_description"])

    def test_resolve_topic_voice_prefers_topic_then_settings_then_default(self):
        # 1. Topic voice
        self.assertEqual(
            auto_producer.resolve_topic_voice(
                {"voice_name": "gemini:Sulafat-Warm"},
                {"voice_name": "gemini:Charon-Male"},
            ),
            "gemini:Sulafat-Warm",
        )
        # 2. Settings voice
        self.assertEqual(
            auto_producer.resolve_topic_voice({}, {"voice_name": "gemini:Charon-Male"}),
            "gemini:Charon-Male",
        )
        # 3. Default fallback
        self.assertEqual(
            auto_producer.resolve_topic_voice({}, {}),
            "gemini:Charon-Informative",
        )

    @patch("scripts.auto_producer.save_topics_data")
    @patch("scripts.auto_producer.load_topics_data")
    @patch("scripts.auto_producer.mpt_create_task")
    @patch("scripts.auto_producer.mpt_update_script")
    @patch("scripts.auto_producer.mpt_synthesize_voice")
    @patch("scripts.auto_producer.mpt_generate_subtitles")
    @patch("scripts.auto_producer.mpt_fetch_materials")
    @patch("scripts.auto_producer.mpt_render_video")
    @patch("scripts.auto_producer.UploadPostService")
    @patch("scripts.auto_producer.prune_old_storage")
    @patch("scripts.auto_producer.refill_topics_if_needed")
    @patch("os.path.isfile")
    @patch("os.path.getsize")
    def test_run_production_records_requested_voice_on_success(
        self,
        mock_getsize,
        mock_isfile,
        mock_refill,
        mock_prune,
        mock_upload_post,
        mock_render,
        mock_fetch,
        mock_sub,
        mock_synth,
        mock_update,
        mock_create,
        mock_load,
        mock_save,
    ):
        mock_topic = {
            "id": "topic_083",
            "subject": "Apophis 2029",
            "editorial_version": "retention-v1",
            "youtube_title": "Apofis pasará dentro de la órbita satelital",
            "script": "Apofis pasará más cerca que muchos satélites. [pause:0.4] El 13 de abril de 2029, este asteroide de unos 340 metros cruzará a solo 32.000 kilómetros de la superficie terrestre. No chocará con nosotros: la gravedad de la Tierra alterará su órbita y podría sacudir su superficie.",
            "search_terms": [
                "Apophis asteroid space animation Earth",
                "geostationary satellites orbiting planet Earth",
                "large rocky asteroid close up",
                "asteroid passing near blue Earth",
                "spacecraft observing asteroid rocky surface",
            ],
            "tags": ["shorts"],
            "voice_name": "gemini:Charon-Informative",
            "experiment_variant": "A",
            "status": "pending",
        }
        mock_load.return_value = {
            "schedule_settings": {},
            "topics": [mock_topic],
        }
        mock_create.return_value = {"task_id": "test-task-voice"}
        mock_synth.return_value = {"success": True, "audio_file": "audio.mp3"}
        mock_render.return_value = {"videos": ["final-1.mp4"]}
        mock_isfile.return_value = True
        mock_getsize.return_value = 5_000_000

        result = auto_producer.run_production(auto_publish=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["voice_used"], "gemini:Charon-Informative")
        self.assertFalse(result["voice_fallback"])
        self.assertEqual(mock_topic["voice_used"], "gemini:Charon-Informative")
        self.assertFalse(mock_topic["voice_fallback"])
        mock_synth.assert_called_once_with(
            task_id="test-task-voice", voice_name="gemini:Charon-Informative"
        )

    @patch("scripts.auto_producer.save_topics_data")
    @patch("scripts.auto_producer.load_topics_data")
    @patch("scripts.auto_producer.mpt_create_task")
    @patch("scripts.auto_producer.mpt_update_script")
    @patch("scripts.auto_producer.mpt_synthesize_voice")
    @patch("scripts.auto_producer.mpt_generate_subtitles")
    @patch("scripts.auto_producer.mpt_fetch_materials")
    @patch("scripts.auto_producer.mpt_render_video")
    @patch("scripts.auto_producer.UploadPostService")
    @patch("scripts.auto_producer.prune_old_storage")
    @patch("scripts.auto_producer.refill_topics_if_needed")
    @patch("os.path.isfile")
    @patch("os.path.getsize")
    def test_run_production_falls_back_on_unsuccessful_voice_result(
        self,
        mock_getsize,
        mock_isfile,
        mock_refill,
        mock_prune,
        mock_upload_post,
        mock_render,
        mock_fetch,
        mock_sub,
        mock_synth,
        mock_update,
        mock_create,
        mock_load,
        mock_save,
    ):
        mock_topic = {
            "id": "topic_084",
            "subject": "Toba Supervolcano",
            "editorial_version": "retention-v1",
            "youtube_title": "Toba cubrió de ceniza medio planeta entero",
            "script": "Toba dejó una cicatriz de escala provincial. [pause:0.4] Hace 74.000 años, su supererupción expulsó miles de kilómetros cúbicos de material y levantó la enorme caldera que hoy ocupa el lago Toba. La ceniza cubrió unos 40 millones de kilómetros cuadrados: una huella todavía visible en el paisaje.",
            "search_terms": [
                "aerial view Lake Toba Indonesia caldera",
                "massive volcanic eruption ash cloud",
                "volcanic ash covering tropical landscape",
                "satellite view Sumatra Indonesia lake",
                "steep caldera cliffs Lake Toba",
            ],
            "tags": ["shorts"],
            "voice_name": "gemini:Sulafat-Warm",
            "experiment_variant": "B",
            "status": "pending",
        }
        mock_load.return_value = {
            "schedule_settings": {},
            "topics": [mock_topic],
        }
        mock_create.return_value = {"task_id": "test-task-fallback"}
        # First call fails, second call (fallback) succeeds
        mock_synth.side_effect = [
            {"success": False, "error": "Quota exceeded"},
            {"success": True, "audio_file": "audio.mp3"},
        ]
        mock_render.return_value = {"videos": ["final-1.mp4"]}
        mock_isfile.return_value = True
        mock_getsize.return_value = 5_000_000

        result = auto_producer.run_production(auto_publish=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["voice_used"], "es-ES-AlvaroNeural")
        self.assertTrue(result["voice_fallback"])
        self.assertEqual(mock_topic["voice_used"], "es-ES-AlvaroNeural")
        self.assertTrue(mock_topic["voice_fallback"])
        self.assertEqual(mock_synth.call_count, 2)

    @patch("scripts.auto_producer.save_topics_data")
    @patch("scripts.auto_producer.load_topics_data")
    @patch("scripts.auto_producer.mpt_create_task")
    @patch("scripts.auto_producer.mpt_update_script")
    @patch("scripts.auto_producer.mpt_synthesize_voice")
    @patch("scripts.auto_producer.mpt_generate_subtitles")
    @patch("scripts.auto_producer.mpt_fetch_materials")
    @patch("scripts.auto_producer.mpt_render_video")
    @patch("scripts.auto_producer.UploadPostService")
    @patch("scripts.auto_producer.prune_old_storage")
    @patch("scripts.auto_producer.refill_topics_if_needed")
    @patch("os.path.isfile")
    @patch("os.path.getsize")
    def test_run_production_falls_back_on_voice_exception(
        self,
        mock_getsize,
        mock_isfile,
        mock_refill,
        mock_prune,
        mock_upload_post,
        mock_render,
        mock_fetch,
        mock_sub,
        mock_synth,
        mock_update,
        mock_create,
        mock_load,
        mock_save,
    ):
        mock_topic = {
            "id": "topic_085",
            "subject": "Kamchatka 1952",
            "editorial_version": "retention-v1",
            "youtube_title": "El tsunami de Kamchatka cruzó el Pacífico",
            "script": "Un terremoto envió una ola a otro continente. [pause:0.4] El 4 de noviembre de 1952, un sismo de magnitud 9 frente a Kamchatka generó olas locales de 13 metros. Horas después, el tsunami alcanzó Hawái y quedó registrado por mareógrafos en decenas de estaciones alrededor de todo el Pacífico.",
            "search_terms": [
                "Kamchatka volcanic peninsula snowy coast",
                "powerful ocean earthquake seismic waves",
                "massive tsunami wave open ocean",
                "Hawaii coastline powerful incoming waves",
                "vintage tide gauge ocean station",
            ],
            "tags": ["shorts"],
            "voice_name": "gemini:Charon-Informative",
            "experiment_variant": "A",
            "status": "pending",
        }
        mock_load.return_value = {
            "schedule_settings": {},
            "topics": [mock_topic],
        }
        mock_create.return_value = {"task_id": "test-task-exc"}
        mock_synth.side_effect = [
            Exception("Network error"),
            {"success": True, "audio_file": "audio.mp3"},
        ]
        mock_render.return_value = {"videos": ["final-1.mp4"]}
        mock_isfile.return_value = True
        mock_getsize.return_value = 5_000_000

        result = auto_producer.run_production(auto_publish=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["voice_used"], "es-ES-AlvaroNeural")
        self.assertTrue(result["voice_fallback"])

    @patch("scripts.auto_producer.load_topics_data")
    @patch("scripts.auto_producer.prune_old_storage")
    @patch("scripts.auto_producer.refill_topics_if_needed")
    def test_run_production_skips_if_experiment_variant_already_published_today(
        self, mock_refill, mock_prune, mock_load
    ):
        today_str = datetime.now().strftime("%Y-%m-%d")
        past_topic = {
            "id": "topic_083",
            "subject": "Apophis 2029",
            "experiment_variant": "A",
            "status": "published",
            "rendered_at": f"{today_str}T19:30:00",
        }
        next_topic = {
            "id": "topic_084",
            "subject": "Toba",
            "experiment_variant": "B",
            "status": "pending",
        }
        mock_load.return_value = {
            "schedule_settings": {},
            "topics": [past_topic, next_topic],
        }
        result = auto_producer.run_production(auto_publish=False)
        self.assertTrue(result["success"])
        self.assertTrue(result.get("skipped"))
        self.assertIn(
            "Already published an experiment variant today",
            result.get("reason", ""),
        )

    def test_retention_experiment_topics_are_valid_and_balanced(self):
        data = auto_producer.load_topics_data()
        settings = data.get("schedule_settings", {})
        self.assertEqual(settings.get("daily_slots"), ["19:30"])
        self.assertEqual(settings.get("voice_name"), "gemini:Charon-Informative")

        topics = {t["id"]: t for t in data.get("topics", [])}
        exp_ids = [
            "topic_100",
            "topic_101",
            "topic_102",
            "topic_103",
            "topic_104",
            "topic_105",
        ]
        expected_variants = ["A", "B", "A", "B", "A", "B"]
        expected_voices = [
            "gemini:Charon-Informative",
            "gemini:Sulafat-Warm",
            "gemini:Charon-Informative",
            "gemini:Sulafat-Warm",
            "gemini:Charon-Informative",
            "gemini:Sulafat-Warm",
        ]

        for topic_id, exp_var, exp_voice in zip(
            exp_ids, expected_variants, expected_voices
        ):
            self.assertIn(topic_id, topics)
            t = topics[topic_id]
            self.assertEqual(t.get("editorial_version"), "retention-v1")
            self.assertEqual(t.get("experiment_variant"), exp_var)
            self.assertEqual(t.get("voice_name"), exp_voice)
            self.assertTrue(t.get("youtube_title"))
            self.assertEqual(len(t.get("search_terms", [])), 5)
            # Must pass strict editorial validation
            auto_producer.validate_topic_for_production(t)

        # Verify topic_106 and topic_107 remain clean pending legacy topics
        for legacy_id in ["topic_106", "topic_107"]:
            self.assertIn(legacy_id, topics)
            t = topics[legacy_id]
            self.assertEqual(t.get("status"), "pending")
            self.assertNotIn("experiment_variant", t)
            self.assertNotIn("voice_name", t)
            self.assertNotIn("editorial_version", t)


if __name__ == "__main__":
    unittest.main()
