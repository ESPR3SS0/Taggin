import io
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from taggin import (
    ConsoleTagFirstFormatter,
    LogStorage,
    StructuredLogEntry,
    set_tag_style,
)
from taggin import log as taggin_log


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


def test_fuzzy_search_handles_non_positive_limits():
    storage = LogStorage()
    storage.add(make_entry(0, None, "alpha"))
    storage.add(make_entry(1, None, "beta"))

    assert storage.search_fuzzy("alpha", limit=0) == []
    assert storage.search_fuzzy("alpha", limit=-1) == []


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
        record.tag = tag
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


class _MemoryStream:
    def __init__(self):
        self.writes: list[str] = []
        self.flush_count = 0

    def write(self, msg: str) -> None:
        self.writes.append(msg)

    def flush(self) -> None:
        self.flush_count += 1


def _build_progress_handler(stream: _MemoryStream) -> taggin_log.ProgressSafeStreamHandler:
    handler = taggin_log.ProgressSafeStreamHandler()
    handler.setStream(stream)  # type: ignore[arg-type]
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def _make_simple_record(message: str = "payload") -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 0, message, args=(), exc_info=None)


def test_progress_handler_plain_stream(monkeypatch):
    stream = _MemoryStream()
    handler = _build_progress_handler(stream)
    monkeypatch.setattr(taggin_log, "_tqdm_write", None)
    monkeypatch.setattr(taggin_log, "_alive_write", None)
    handler.emit(_make_simple_record("hello"))
    assert stream.writes == ["hello\n"]
    assert stream.flush_count == 1


def test_progress_handler_yaspin_like_stream(monkeypatch):
    class _YaspinStream:
        def __init__(self):
            self.output = []
            self.flush_count = 0

        def write(self, msg: str):
            self.output.append(msg.replace("\r", ""))

        def flush(self):
            self.flush_count += 1

    stream = _YaspinStream()
    handler = _build_progress_handler(stream)  # type: ignore[arg-type]
    monkeypatch.setattr(taggin_log, "_tqdm_write", None)
    monkeypatch.setattr(taggin_log, "_alive_write", None)
    handler.emit(_make_simple_record("tick\rspin"))
    assert "tickspin\n" in stream.output or "tickspin" in stream.output[0]
    assert stream.flush_count == 1


def test_progress_handler_prefers_tqdm(monkeypatch):
    calls: list[SimpleNamespace] = []

    def fake_tqdm_write(message: str, *, file):
        calls.append(SimpleNamespace(message=message, file=file))

    stream = _MemoryStream()
    handler = _build_progress_handler(stream)
    monkeypatch.setattr(taggin_log, "_tqdm_write", fake_tqdm_write)
    monkeypatch.setattr(taggin_log, "_alive_write", None)
    handler.emit(_make_simple_record("via tqdm"))

    assert calls and calls[0].message == "via tqdm"
    assert calls[0].file is stream
    assert stream.writes == []


def test_progress_handler_alive_with_stream_arg(monkeypatch):
    calls = []

    def fake_alive(message: str, *, file):
        calls.append((message, file))

    stream = _MemoryStream()
    handler = _build_progress_handler(stream)
    monkeypatch.setattr(taggin_log, "_tqdm_write", None)
    monkeypatch.setattr(taggin_log, "_alive_write", fake_alive)
    monkeypatch.setattr(taggin_log, "_ALIVE_WRITE_ACCEPTS_STREAM", True)

    handler.emit(_make_simple_record("alive stream"))
    assert calls == [("alive stream", stream)]
    assert stream.writes == []


def test_progress_handler_alive_without_stream_arg(monkeypatch):
    calls = []

    def fake_alive(message: str):
        calls.append(message)

    stream = _MemoryStream()
    handler = _build_progress_handler(stream)
    monkeypatch.setattr(taggin_log, "_tqdm_write", None)
    monkeypatch.setattr(taggin_log, "_alive_write", fake_alive)
    monkeypatch.setattr(taggin_log, "_ALIVE_WRITE_ACCEPTS_STREAM", False)

    handler.emit(_make_simple_record("alive simple"))
    assert calls == ["alive simple"]
    assert stream.writes == []


def test_progress_handler_alive_typeerror_fallback(monkeypatch):
    calls = []

    def fake_alive(message: str, **kwargs):
        calls.append((message, kwargs))
        if "file" in kwargs:
            raise TypeError("no file parameter")

    stream = _MemoryStream()
    handler = _build_progress_handler(stream)
    monkeypatch.setattr(taggin_log, "_tqdm_write", None)
    monkeypatch.setattr(taggin_log, "_alive_write", fake_alive)
    monkeypatch.setattr(taggin_log, "_ALIVE_WRITE_ACCEPTS_STREAM", True)

    handler.emit(_make_simple_record("alive fallback"))
    assert calls == [("alive fallback", {"file": stream}), ("alive fallback", {})]
    assert stream.writes == []


def test_progress_handler_alive_error_fallback_to_stream(monkeypatch):
    class Boom(Exception):
        pass

    def fake_alive(message: str, **kwargs):
        raise Boom("oops")

    stream = _MemoryStream()
    handler = _build_progress_handler(stream)
    monkeypatch.setattr(taggin_log, "_tqdm_write", None)
    monkeypatch.setattr(taggin_log, "_alive_write", fake_alive)
    monkeypatch.setattr(taggin_log, "_ALIVE_WRITE_ACCEPTS_STREAM", True)

    handler.emit(_make_simple_record("alive boom"))
    assert stream.writes == ["alive boom\n"]


def test_progress_handler_switches_to_rich_proxy(monkeypatch):
    class _ProxyStream:
        def __init__(self):
            self.output: list[str] = []
            self.flush_count = 0

        def write(self, msg: str):
            self.output.append(msg)

        def flush(self):
            self.flush_count += 1

    base_stream = _MemoryStream()
    monkeypatch.setattr(taggin_log.sys, "stderr", base_stream)
    handler = taggin_log.ProgressSafeStreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr(taggin_log, "_RICH_FILE_PROXY", _ProxyStream)

    proxy = _ProxyStream()
    taggin_log.sys.stderr = proxy

    handler.emit(_make_simple_record("rich progress"))

    assert handler.stream is proxy
    assert proxy.output == ["rich progress\n"]
    assert proxy.flush_count == 1


def test_progress_handler_returns_from_rich_proxy(monkeypatch):
    class _ProxyStream:
        def __init__(self):
            self.output: list[str] = []

        def write(self, msg: str):
            self.output.append(msg)

        def flush(self):
            pass

    initial_stream = _MemoryStream()
    monkeypatch.setattr(taggin_log.sys, "stderr", initial_stream)
    handler = taggin_log.ProgressSafeStreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    monkeypatch.setattr(taggin_log, "_RICH_FILE_PROXY", _ProxyStream)

    proxy = _ProxyStream()
    taggin_log.sys.stderr = proxy
    handler.emit(_make_simple_record("proxy one"))
    assert handler.stream is proxy
    assert proxy.output == ["proxy one\n"]

    restored = _MemoryStream()
    taggin_log.sys.stderr = restored
    handler.emit(_make_simple_record("back to normal"))
    assert handler.stream is restored
    assert restored.writes == ["back to normal\n"]


def test_progress_handler_with_real_rich_progress(monkeypatch):
    from rich.console import Console
    from rich.progress import Progress

    if taggin_log._RICH_FILE_PROXY is None:
        pytest.skip("Rich FileProxy unavailable")

    console_buffer = io.StringIO()
    console = Console(file=console_buffer, force_terminal=True, force_interactive=True)
    base_stream = _MemoryStream()
    monkeypatch.setattr(taggin_log.sys, "stderr", base_stream)

    handler = taggin_log.ProgressSafeStreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))

    with Progress(console=console, auto_refresh=False, transient=True) as progress:
        handler.emit(_make_simple_record("rich live"))
        assert isinstance(handler.stream, taggin_log._RICH_FILE_PROXY)
        progress.refresh()

    output = console_buffer.getvalue()
    assert "rich live" in output


def test_tagged_logs_visible_with_high_console_level(tmp_path, monkeypatch):
    prev_visible = taggin_log.get_visible_tags()
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    for handler in original_handlers:
        root.removeHandler(handler)

    buffer = io.StringIO()
    monkeypatch.setattr(taggin_log.sys, "stderr", buffer)

    logger = taggin_log.setup_logger(log_dir=tmp_path, console_level="WARNING")
    taggin_log.set_visible_tags(["TRAIN.*"])

    buffer.truncate(0)
    buffer.seek(0)
    logger.TRAIN.START("visible info")
    assert "visible info" in buffer.getvalue()

    buffer.truncate(0)
    buffer.seek(0)
    logger.info("untagged info")
    assert buffer.getvalue() == ""

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    for handler in original_handlers:
        root.addHandler(handler)

    if prev_visible is None:
        taggin_log.set_visible_tags(["*"])
    elif len(prev_visible) == 0:
        taggin_log.set_visible_tags(None)
    else:
        taggin_log.set_visible_tags(prev_visible)
    taggin_log._set_console_level_threshold(logging.INFO)
