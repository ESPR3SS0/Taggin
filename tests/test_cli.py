import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from taggin.cli import by_date, by_tag, fuzzy, tags
from taggin import LogStorage, StructuredLogEntry


@pytest.fixture()
def structured_log(tmp_path):
    storage = LogStorage()
    base = datetime(2025, 1, 1, 12, 0, 0)
    entries = [
        StructuredLogEntry(base, "INFO", "demo", "TRAIN.START", "epoch 0"),
        StructuredLogEntry(base + timedelta(seconds=10), "INFO", "demo", "TRAIN.END", "epoch done"),
        StructuredLogEntry(base + timedelta(seconds=20), "INFO", "demo", "IO.net", "connected to redis"),
    ]
    for entry in entries:
        storage.add(entry)
    path = Path(tmp_path) / "structured.log"
    storage.save_text(path)
    return path, entries


def test_cli_by_tag_text_output(structured_log, capsys):
    path, _ = structured_log
    by_tag(path, "TRAIN.*")
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2
    assert "[TRAIN.START]" in out[0]
    assert "[TRAIN.END]" in out[1]


def test_cli_by_tag_json_output(structured_log, capsys):
    path, _ = structured_log
    by_tag(path, "TRAIN.*", json_output=True)
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 2
    assert data[0]["tag"] == "TRAIN.START"


def test_cli_by_date_range(structured_log, capsys):
    path, entries = structured_log
    start = entries[0].timestamp.isoformat()
    end = entries[1].timestamp.isoformat()
    by_date(path, start=start, end=end)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2  # includes start/end entries


def test_cli_fuzzy_limit(structured_log, capsys):
    path, _ = structured_log
    fuzzy(path, "redis", threshold=0.3, limit=1)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert "redis" in out[0]


def test_cli_list_tags(structured_log, capsys):
    path, _ = structured_log
    tags(path)
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["IO.net", "TRAIN.END", "TRAIN.START"]

    tags(path, json_output=True)
    json_data = json.loads(capsys.readouterr().out)
    assert json_data == ["IO.net", "TRAIN.END", "TRAIN.START"]
