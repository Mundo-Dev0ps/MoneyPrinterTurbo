import json
import os
import tempfile
from pathlib import Path

import pytest

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


def test_task_resource_missing():
    from app.mcp.server import get_task_script_resource, get_task_subtitles_resource, get_task_summary_resource

    res_script = get_task_script_resource("fake-task-id")
    assert "error" in res_script.lower() or "not found" in res_script.lower()

    res_sub = get_task_subtitles_resource("fake-task-id")
    assert "error" in res_sub.lower() or "not found" in res_sub.lower()

    res_sum = get_task_summary_resource("fake-task-id")
    assert "error" in res_sum.lower() or "not found" in res_sum.lower()


def test_task_resources_existing():
    from app.mcp.server import (
        mpt_create_task,
        mpt_update_script,
        get_task_script_resource,
        get_task_subtitles_resource,
        get_task_summary_resource,
    )
    from app.services import task_artifacts

    task = mpt_create_task(subject="Resource Test Video")
    task_id = task["task_id"]
    task_dir = utils.task_dir(task_id)

    mpt_update_script(task_id, script_text="Testing MCP resources in MoneyPrinterTurbo.", terms=["test term"])

    srt_path = os.path.join(task_dir, "subtitle.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,000 --> 00:00:03,000\nTesting MCP resources in MoneyPrinterTurbo.\n\n")

    task_artifacts.patch_script_data(task_id, subtitle_path=srt_path)

    # 1. Test script resource
    res_script = get_task_script_resource(task_id)
    assert "Testing MCP resources" in res_script

    # 2. Test subtitle resource
    res_sub = get_task_subtitles_resource(task_id)
    assert "00:00:00,000" in res_sub

    # 3. Test summary resource
    res_sum = get_task_summary_resource(task_id)
    sum_data = json.loads(res_sum)
    assert sum_data.get("task_id") == task_id
    assert sum_data.get("subject") == "Resource Test Video"
