import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from taggin import LogStorage, StructuredLogEntry
from taggin.cli import by_date, by_tag, fuzzy, tags


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
    output = capsys.readouterr().out
    assert "Tag" in output
    assert "Count" in output
    assert "TRAIN.START" in output
    assert "TRAIN.END" in output
    assert "IO.net" in output

    tags(path, json_output=True)
    json_data = json.loads(capsys.readouterr().out)
    assert json_data == [
        {"tag": "IO.net", "count": 1},
        {"tag": "TRAIN.END", "count": 1},
        {"tag": "TRAIN.START", "count": 1},
    ]


def test_cli_tags_sorted_with_counts(tmp_path, capsys):
    storage = LogStorage()
    base = datetime(2025, 1, 1, 12, 0, 0)
    entries = [
        StructuredLogEntry(base, "INFO", "demo", "HOT", "first"),
        StructuredLogEntry(base + timedelta(seconds=1), "INFO", "demo", "COLD", "second"),
        StructuredLogEntry(base + timedelta(seconds=2), "INFO", "demo", "HOT", "third"),
    ]
    for entry in entries:
        storage.add(entry)
    path = Path(tmp_path) / "tags.log"
    storage.save_text(path)

    tags(path)
    output = capsys.readouterr().out
    assert output.index("HOT") < output.index("COLD")
    assert "HOT" in output and "2" in output
    assert "COLD" in output and "1" in output

    tags(path, json_output=True)
    json_data = json.loads(capsys.readouterr().out)
    assert json_data == [
        {"tag": "HOT", "count": 2},
        {"tag": "COLD", "count": 1},
    ]


def test_cli_skips_malformed_text_lines(tmp_path, capsys):
    path = Path(tmp_path) / "bad.log"
    path.write_text(
        "\n".join(
            [
                "not even close",  # missing separators
                "2025-01-01T12:00:00 | INFO | demo | [TRAIN.START] ok",  # valid
                "invalid-timestamp | INFO | demo | [TRAIN.END] bad",  # invalid ts
            ]
        )
    )

    by_tag(path, "TRAIN.*")
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["2025-01-01T12:00:00 | INFO    | demo | [TRAIN.START] ok"]


def test_cli_ignores_blank_date_filters(structured_log, capsys):
    path, entries = structured_log
    by_date(path, start="   ", end=None)
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == len(entries)


def test_cli_invalid_date_string_raises(structured_log):
    path, _ = structured_log
    with pytest.raises(ValueError):
        by_date(path, start="not-a-date")
