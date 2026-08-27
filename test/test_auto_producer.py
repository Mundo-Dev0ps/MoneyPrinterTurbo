import os
import json
import unittest
from unittest.mock import patch, MagicMock

from scripts import auto_producer


class TestAutoProducer(unittest.TestCase):
    def test_imports_and_symbols(self):
        """Verifica que todos los módulos y funciones requeridos por auto_producer existen."""
        self.assertTrue(hasattr(auto_producer, "run_production"))
        self.assertTrue(hasattr(auto_producer, "load_topics_data"))
        self.assertTrue(hasattr(auto_producer, "save_topics_data"))
        self.assertTrue(hasattr(auto_producer, "UploadPostService"))
        self.assertTrue(hasattr(auto_producer, "mpt_create_task"))
        self.assertTrue(hasattr(auto_producer, "mpt_update_script"))
        self.assertTrue(hasattr(auto_producer, "mpt_synthesize_voice"))
        self.assertTrue(hasattr(auto_producer, "mpt_generate_subtitles"))
        self.assertTrue(hasattr(auto_producer, "mpt_fetch_materials"))
        self.assertTrue(hasattr(auto_producer, "mpt_render_video"))

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
    ):
        """Valida que run_production ejecuta el flujo completo e instancia y llama a UploadPostService correctamente."""
        mock_data = {
            "schedule_settings": {
                "platforms": ["youtube", "instagram"],
                "user_name": "ErDivertido"
            },
            "topics": [
                {
                    "id": "test_topic_001",
                    "subject": "¿Es posible viajar en el tiempo? 😱",
                    "script": "Texto de prueba para el video.",
                    "status": "pending",
                    "tags": ["ciencia", "espacio"],
                    "search_terms": ["time travel space stars"]
                }
            ]
        }
        mock_load_topics.return_value = mock_data
        mock_create_task.return_value = {"task_id": "test-task-1234"}
        mock_update_script.return_value = {"success": True}
        mock_synth_voice.return_value = {"success": True, "audio_file": "audio.mp3", "audio_duration": 30}
        mock_gen_subtitles.return_value = {"success": True}
        mock_fetch_mat.return_value = {"success": True, "downloaded_count": 5}
        mock_render_vid.return_value = {
            "success": True,
            "videos": ["storage/tasks/test-task-1234/final-1.mp4"],
            "combined_videos": ["storage/tasks/test-task-1234/combined-1.mp4"],
            "warnings": []
        }

        # Setup mock file checks for QA gates
        mock_isfile.return_value = True
        mock_getsize.side_effect = lambda f: 100 if "subtitle.srt" in f else 10_000_000

        # Setup mock UploadPostService instance
        mock_ups_instance = MagicMock()
        mock_ups_instance.upload_video.return_value = {
            "success": True,
            "request_id": "req-123",
            "job_id": "job-456"
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
    ):
        """Valida que el QA Gate 1 aborta la producción si subtitle.srt no existe o está vacío."""
        mock_data = {
            "schedule_settings": {},
            "topics": [
                {
                    "id": "test_topic_002",
                    "subject": "Tema sin subtitulos",
                    "script": "Texto de prueba.",
                    "status": "pending"
                }
            ]
        }
        mock_load_topics.return_value = mock_data
        mock_create_task.return_value = {"task_id": "test-task-sub-fail"}
        mock_synth_voice.return_value = {"success": True, "audio_file": "audio.mp3", "audio_duration": 30}
        mock_gen_subtitles.return_value = {"success": True}

        # Mock missing subtitle file
        mock_isfile.return_value = False

        with self.assertRaises(RuntimeError) as ctx:
            auto_producer.run_production(auto_publish=True)
        self.assertIn("QA GATE FAILED", str(ctx.exception))

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
    ):
        """Valida que el QA Gate 2 aborta la producción si final-1.mp4 pesa menos de 1 MB."""
        mock_data = {
            "schedule_settings": {},
            "topics": [
                {
                    "id": "test_topic_003",
                    "subject": "Tema video corrupto",
                    "script": "Texto de prueba.",
                    "status": "pending"
                }
            ]
        }
        mock_load_topics.return_value = mock_data
        mock_create_task.return_value = {"task_id": "test-task-corrupt"}
        mock_update_script.return_value = {"success": True}
        mock_synth_voice.return_value = {"success": True, "audio_file": "audio.mp3", "audio_duration": 30}
        mock_gen_subtitles.return_value = {"success": True}
        mock_fetch_mat.return_value = {"success": True, "downloaded_count": 5}
        mock_render_vid.return_value = {
            "success": True,
            "videos": ["storage/tasks/test-task-corrupt/final-1.mp4"],
            "warnings": []
        }

        mock_isfile.return_value = True
        # Subtitle is good (500 bytes), but video file is only 500 bytes (corrupt/empty)
        mock_getsize.side_effect = lambda f: 500 if "subtitle.srt" in f else 500

        with self.assertRaises(RuntimeError) as ctx:
            auto_producer.run_production(auto_publish=True)
        self.assertIn("QA GATE FAILED", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
