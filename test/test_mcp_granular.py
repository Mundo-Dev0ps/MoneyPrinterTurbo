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



def test_granular_imports():
    from app.mcp.server import (
        mpt_create_task,
        mpt_generate_script,
        mpt_update_script,
        mpt_synthesize_voice,
        mpt_generate_subtitles,
        mpt_fetch_materials,
        mpt_inspect_materials,
        mpt_replace_scene_material,
    )

    assert callable(mpt_create_task)
    assert callable(mpt_generate_script)
    assert callable(mpt_update_script)
    assert callable(mpt_synthesize_voice)
    assert callable(mpt_generate_subtitles)
    assert callable(mpt_fetch_materials)
    assert callable(mpt_inspect_materials)
    assert callable(mpt_replace_scene_material)


def test_mpt_create_task():
    from app.mcp.server import mpt_create_task

    res = mpt_create_task(subject="Test AI Video", aspect="9:16", language="es")
    assert isinstance(res, dict)
    assert res.get("success") is True
    task_id = res.get("task_id")
    assert task_id is not None
    assert len(task_id) > 0

    task_dir = utils.task_dir(task_id)
    assert os.path.isdir(task_dir)
    script_file = os.path.join(task_dir, "script.json")
    assert os.path.isfile(script_file)

    with open(script_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "params" in data
    assert data["params"]["video_subject"] == "Test AI Video"


def test_mpt_generate_script_mocked():
    from app.mcp.server import mpt_create_task, mpt_generate_script

    task = mpt_create_task(subject="AI in Medicine", aspect="16:9", language="en")
    task_id = task["task_id"]

    mock_script = "Artificial intelligence is transforming modern healthcare."
    mock_terms = ["artificial intelligence", "hospital doctor", "robotics surgery"]

    with patch("app.services.llm.generate_script", return_value=mock_script) as mock_gen_s, \
         patch("app.services.llm.generate_terms", return_value=mock_terms) as mock_gen_t:
        res = mpt_generate_script(task_id=task_id, prompt_hint="Focus on robotic surgery")
        assert res.get("success") is True
        assert res.get("script") == mock_script
        assert res.get("search_terms") == mock_terms

    task_dir = utils.task_dir(task_id)
    script_file = os.path.join(task_dir, "script.json")
    with open(script_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data["script"] == mock_script
    assert saved_data["search_terms"] == mock_terms


def test_mpt_update_script():
    from app.mcp.server import mpt_create_task, mpt_update_script

    task = mpt_create_task(subject="Renewable Energy")
    task_id = task["task_id"]

    new_script = "Solar and wind energy are leading the clean transition."
    new_terms = ["solar panels", "wind turbine farm"]

    res = mpt_update_script(task_id=task_id, script_text=new_script, terms=new_terms)
    assert res.get("success") is True
    assert res.get("script") == new_script
    assert res.get("search_terms") == new_terms

    # Test with comma-separated string terms
    res2 = mpt_update_script(task_id=task_id, script_text=new_script, terms="solar panels, wind turbines, battery")
    assert res2.get("success") is True
    assert res2.get("search_terms") == ["solar panels", "wind turbines", "battery"]


def test_mpt_synthesize_voice_mocked():
    from app.mcp.server import mpt_create_task, mpt_update_script, mpt_synthesize_voice

    task = mpt_create_task(subject="Ocean Wonders")
    task_id = task["task_id"]
    mpt_update_script(task_id=task_id, script_text="The ocean is full of fascinating creatures.")

    task_dir = utils.task_dir(task_id)
    expected_audio_file = os.path.join(task_dir, "audio.mp3")

    mock_submaker = MagicMock()
    with patch("app.services.voice.tts", return_value=mock_submaker) as mock_tts, \
         patch("app.services.voice.get_audio_duration", return_value=8.5):
        # Create empty audio file to simulate tts writing output
        with open(expected_audio_file, "wb") as f:
            f.write(b"mock audio content")

        res = mpt_synthesize_voice(task_id=task_id, voice_name="en-US-JennyNeural-Female", voice_rate=1.1)
        assert res.get("success") is True
        assert res.get("audio_file") == expected_audio_file
        assert res.get("audio_duration") == 9  # math.ceil(8.5)


def test_mpt_generate_subtitles_mocked():
    from app.mcp.server import mpt_create_task, mpt_update_script, mpt_generate_subtitles

    task = mpt_create_task(subject="Deep Space")
    task_id = task["task_id"]
    mpt_update_script(task_id=task_id, script_text="Galaxies are vast systems of stars.")

    task_dir = utils.task_dir(task_id)
    srt_file = os.path.join(task_dir, "subtitle.srt")
    with open(srt_file, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,000 --> 00:00:04,000\nGalaxies are vast systems of stars.\n\n")

    res = mpt_generate_subtitles(
        task_id=task_id,
        font_name="STHeitiMedium.ttc",
        text_color="#FFDD00",
        font_size=55,
        subtitle_position="bottom",
    )
    assert res.get("success") is True
    assert res.get("subtitle_file") == srt_file
    assert res.get("font_name") == "STHeitiMedium.ttc"
    assert res.get("text_color") == "#FFDD00"
    assert res.get("font_size") == 55
    assert res.get("subtitle_count") == 1


def test_mpt_fetch_materials_mocked():
    from app.mcp.server import mpt_create_task, mpt_update_script, mpt_fetch_materials

    task = mpt_create_task(subject="Rainforest")
    task_id = task["task_id"]
    mpt_update_script(task_id=task_id, script_text="Rainforests are Earth's lungs.", terms=["rainforest canopy", "waterfall jungle"])

    mock_downloaded = [
        os.path.join(utils.task_dir(task_id), "video_01.mp4"),
        os.path.join(utils.task_dir(task_id), "video_02.mp4"),
    ]

    with patch("app.services.material.download_videos", return_value=mock_downloaded) as mock_dl:
        res = mpt_fetch_materials(task_id=task_id, source="pexels")
        assert res.get("success") is True
        assert res.get("source") == "pexels"
        assert res.get("materials") == mock_downloaded
        assert res.get("material_count") == 2


def test_mpt_inspect_materials():
    from app.mcp.server import mpt_create_task, mpt_update_script, mpt_inspect_materials
    from app.services import task_artifacts

    task = mpt_create_task(subject="Mountain Climbing")
    task_id = task["task_id"]
    mpt_update_script(
        task_id=task_id,
        script_text="Reaching the summit takes endurance.",
        terms=["mountain climber", "snow summit"],
    )

    task_artifacts.patch_script_data(
        task_id,
        material_sources=[
            {"provider": "pexels", "local_file": "vid1.mp4", "duration": 5, "search_term": "mountain climber"},
            {"provider": "pexels", "local_file": "vid2.mp4", "duration": 6, "search_term": "snow summit"},
        ],
        materials=["/path/to/vid1.mp4", "/path/to/vid2.mp4"],
    )

    res = mpt_inspect_materials(task_id=task_id)
    assert isinstance(res, dict)
    assert res.get("success") is True
    assert res.get("task_id") == task_id
    assert res.get("script") == "Reaching the summit takes endurance."
    assert res.get("search_terms") == ["mountain climber", "snow summit"]
    assert len(res.get("scenes", [])) == 2
    assert res.get("scenes")[0]["scene_index"] == 0
    assert res.get("scenes")[0]["term"] == "mountain climber"


def test_mpt_replace_scene_material_local_file():
    from app.mcp.server import mpt_create_task, mpt_update_script, mpt_inspect_materials, mpt_replace_scene_material
    from app.services import task_artifacts

    task = mpt_create_task(subject="Cooking")
    task_id = task["task_id"]
    task_dir = utils.task_dir(task_id)

    dummy_vid1 = os.path.join(task_dir, "clip1.mp4")
    dummy_vid2 = os.path.join(task_dir, "clip2.mp4")
    with open(dummy_vid1, "wb") as f:
        f.write(b"dummy1")
    with open(dummy_vid2, "wb") as f:
        f.write(b"dummy2")

    task_artifacts.patch_script_data(
        task_id,
        materials=[dummy_vid1, dummy_vid2],
        search_terms=["chef cooking", "food plate"],
    )

    # Create a local replacement video file
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(b"new video content")
        replacement_path = tmp.name

    try:
        res = mpt_replace_scene_material(
            task_id=task_id,
            scene_index=1,
            search_query_or_file=replacement_path,
        )
        assert res.get("success") is True
        assert res.get("scene_index") == 1
        assert "materials" in res
        assert len(res["materials"]) == 2
        assert res["materials"][0] == dummy_vid1
        assert res["materials"][1] != dummy_vid2
        assert os.path.isfile(res["materials"][1])
    finally:
        if os.path.exists(replacement_path):
            os.remove(replacement_path)


def test_mpt_replace_scene_material_stock_search():
    from app.mcp.server import mpt_create_task, mpt_replace_scene_material
    from app.services import task_artifacts

    task = mpt_create_task(subject="Wildlife")
    task_id = task["task_id"]
    task_dir = utils.task_dir(task_id)

    dummy_vid1 = os.path.join(task_dir, "lion.mp4")
    with open(dummy_vid1, "wb") as f:
        f.write(b"lion video")

    task_artifacts.patch_script_data(
        task_id,
        materials=[dummy_vid1],
        search_terms=["lion savanna"],
    )

    new_clip = os.path.join(task_dir, "cheetah.mp4")
    with patch("app.services.material.download_videos", return_value=[new_clip]):
        res = mpt_replace_scene_material(
            task_id=task_id,
            scene_index=0,
            search_query_or_file="cheetah running",
        )
        assert res.get("success") is True
        assert res.get("scene_index") == 0
        assert res.get("new_material") == new_clip
        assert res.get("materials")[0] == new_clip
