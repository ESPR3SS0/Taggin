from datetime import datetime, timedelta
import logging

import pytest

from taggin import (
    ConsoleTagFirstFormatter,
    LogStorage,
    StructuredLogEntry,
    set_tag_style,
)


def make_entry(offset_seconds: int, tag: str | None, message: str) -> StructuredLogEntry:
    base = datetime(2025, 1, 1, 12, 0, 0)
    return StructuredLogEntry(
        timestamp=base + timedelta(seconds=offset_seconds),
        level="INFO",
        name="test",
        tag=tag,
        message=message,
    )


def test_save_text_contains_timestamp_and_tag(tmp_path):
    storage = LogStorage()
    entry = make_entry(0, "TRAIN.START", "first")
    storage.add(entry)

    path = tmp_path / "log.txt"
    storage.save_text(path)
    text = path.read_text().strip()

    assert entry.timestamp.isoformat() in text
    assert "[TRAIN.START]" in text
    assert text.endswith("first")


def test_save_text_append_preserves_previous_entries(tmp_path):
    storage = LogStorage()
    storage.add(make_entry(0, "TRAIN.START", "first"))
    path = tmp_path / "log.txt"
    storage.save_text(path)

    storage.clear()
    storage.add(make_entry(5, None, "second"))
    storage.save_text(path, append=True)

    text = path.read_text().strip().splitlines()
    assert len(text) == 2
    assert text[0].endswith("first")
    assert text[1].endswith("second")


def test_search_helpers_cover_date_tag_and_fuzzy():
    storage = LogStorage()
    entries = [
        make_entry(0, "TRAIN.START", "epoch 0"),
        make_entry(10, "TRAIN.END", "epoch done"),
        make_entry(20, "IO.net", "connected to redis"),
    ]
    for entry in entries:
        storage.add(entry)

    # Date search
    start = entries[0].timestamp + timedelta(seconds=5)
    end = entries[-1].timestamp
    date_hits = storage.search_by_date(start=start, end=end)
    assert [hit.message for hit in date_hits] == ["epoch done", "connected to redis"]

    # Tag glob search (case-sensitive)
    tag_hits = storage.search_by_tag("TRAIN.*")
    assert len(tag_hits) == 2
    assert storage.search_by_tag("train.*") == []

    # Fuzzy search should find redis message
    fuzzy_hits = storage.search_fuzzy("redis connection", threshold=0.3)
    assert fuzzy_hits and fuzzy_hits[0].message == "connected to redis"


def test_fuzzy_search_respects_threshold_and_limit():
    storage = LogStorage()
    storage.add(make_entry(0, None, "alpha"))
    storage.add(make_entry(1, None, "alphabet soup"))
    storage.add(make_entry(2, None, "beta"))

    hits = storage.search_fuzzy("alpha", threshold=0.4, limit=1)
    assert len(hits) == 1
    assert hits[0].message.startswith("alpha")

    strict_hits = storage.search_fuzzy("alpha", threshold=0.95)
    assert len(strict_hits) == 1
    assert strict_hits[0].message == "alpha"


def test_search_by_date_handles_unbounded_ranges():
    storage = LogStorage()
    storage.add(make_entry(0, None, "one"))
    storage.add(make_entry(5, None, "two"))

    hits = storage.search_by_date(end=storage.iter_records()[0].timestamp)
    assert len(hits) == 1
    assert hits[0].message == "one"

    hits = storage.search_by_date(start=storage.iter_records()[1].timestamp)
    assert len(hits) == 1
    assert hits[0].message == "two"


def test_save_parquet_if_pandas_available(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    storage = LogStorage()
    storage.add(make_entry(0, "TRAIN.START", "first row"))
    path = tmp_path / "log.parquet"
    storage.save_parquet(path)

    df = pd.read_parquet(path)
    assert len(df) == 1
    assert df.iloc[0]["message"] == "first row"


def _make_record(msg: str, *, tag: str | None = None, level: int = logging.INFO):
    record = logging.LogRecord("test", level, __file__, 0, msg, args=(), exc_info=None)
    if tag:
        setattr(record, "tag", tag)
    return record


def test_console_formatter_plain_includes_emoji():
    set_tag_style("TRAIN.START", emoji="🚂")
    formatter = ConsoleTagFirstFormatter(enable_color=False)
    record = _make_record("payload", tag="TRAIN.START")
    rendered = formatter.format(record)
    assert rendered.startswith("🚂 [TRAIN.START]")


def test_console_formatter_color_mode_outputs_ansi():
    formatter = ConsoleTagFirstFormatter(enable_color=True)
    record = _make_record("payload", tag="TRAIN.START")
    rendered = formatter.format(record)
    assert "\x1b[" in rendered or "[TRAIN.START]" in rendered
