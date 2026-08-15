import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.models.schema import VideoAspect, VideoParams
from app.utils import utils


@pytest.fixture(autouse=True)
def mock_storage(tmp_path, monkeypatch):
    test_storage = tmp_path / "storage"
    test_tasks = test_storage / "tasks"
    test_tasks.mkdir(parents=True, exist_ok=True)

    def fake_task_dir(sub_dir: str = ""):
        d = test_tasks
        if sub_dir:
            d = d / sub_dir
        os.makedirs(str(d), exist_ok=True)
        return str(d)

    def fake_storage_dir(sub_dir: str = "", create: bool = False):
        d = test_storage
        if sub_dir:
            d = d / sub_dir
        if create:
            os.makedirs(str(d), exist_ok=True)
        return str(d)

    monkeypatch.setattr("app.utils.utils.task_dir", fake_task_dir)
    monkeypatch.setattr("app.utils.utils.storage_dir", fake_storage_dir)
    monkeypatch.setattr("app.mcp.server.utils.task_dir", fake_task_dir)
    monkeypatch.setattr("app.mcp.server.utils.storage_dir", fake_storage_dir)
    monkeypatch.setattr("app.services.task_artifacts.utils.task_dir", fake_task_dir)


def test_mpt_get_task_progress_non_existent():
    from app.mcp.server import mpt_get_task_progress

    res = mpt_get_task_progress("non-existent-uuid-12345")
    assert isinstance(res, dict)
    assert res.get("success") is False or res.get("state") in ["not_found", 0, -1]


def test_mpt_render_video_mocked():
    from app.mcp.server import (
        mpt_create_task,
        mpt_update_script,
        mpt_render_video,
    )
    from app.services import task_artifacts

    task = mpt_create_task(subject="Future Cities")
    task_id = task["task_id"]
    task_dir = utils.task_dir(task_id)

    audio_file = os.path.join(task_dir, "audio.mp3")
    subtitle_file = os.path.join(task_dir, "subtitle.srt")
    mat_file = os.path.join(task_dir, "clip.mp4")
    final_mp4 = os.path.join(task_dir, "final-1.mp4")

    with open(audio_file, "wb") as f:
        f.write(b"audio")
    with open(subtitle_file, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,000 --> 00:00:05,000\nHello city\n\n")
    with open(mat_file, "wb") as f:
        f.write(b"video")
    with open(final_mp4, "wb") as f:
        f.write(b"final mp4")

    task_artifacts.patch_script_data(
        task_id,
        audio_file=audio_file,
        audio_duration=5,
        subtitle_path=subtitle_file,
        materials=[mat_file],
    )

    with patch("app.services.task.generate_final_videos", return_value=([final_mp4], [final_mp4], [])):
        res = mpt_render_video(
            task_id=task_id,
            bgm_volume=0.1,
            video_concat_mode="random",
        )
        assert res.get("success") is True
        assert res.get("task_id") == task_id
        assert final_mp4 in res.get("videos", [])


def test_mpt_generate_full_video_mocked():
    from app.mcp.server import mpt_generate_full_video, mpt_get_task_progress

    dummy_task_id = "test-oneshot-task"
    dummy_final_mp4 = "/path/to/final-1.mp4"

    mock_result = {
        "videos": [dummy_final_mp4],
        "combined_videos": [dummy_final_mp4],
        "script": "Sample video script.",
        "terms": ["urban city"],
        "audio_file": "/path/to/audio.mp3",
        "audio_duration": 10,
        "subtitle_path": "/path/to/subtitle.srt",
        "materials": ["/path/to/clip.mp4"],
    }

    with patch("app.services.task.start", return_value=mock_result) as mock_start:
        res = mpt_generate_full_video(
            subject="Urban Architecture",
            aspect="9:16",
            video_source="pexels",
            bgm_volume=0.2,
        )
        assert res.get("success") is True
        assert "task_id" in res
        assert dummy_final_mp4 in res.get("videos", [])

        # Check progress
        progress = mpt_get_task_progress(task_id=res["task_id"])
        assert isinstance(progress, dict)
