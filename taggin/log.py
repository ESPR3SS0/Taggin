from __future__ import annotations

"""
Logging utilities with dynamic tag methods and searchable storage.

Adds lightweight, category-style tagged logging to the standard library logger
while mirroring all emitted records into an in-memory index that can be saved
to text/Parquet and searched by tag, date, or fuzzy message matching.

Usage
-----
- Call `setup_logger()` once at program start.
- Use normal logging as before (debug/info/warning/...).
- Additionally, call arbitrary attributes as methods to emit tagged logs:
    logger.PRUNE("removed 10% rows")
    logger.TRAIN("epoch=%d acc=%.2f", ep, acc)
    logger.QUANT("applied 4-bit plan")
    logger.QAT.FOLD("folded layers")           # hierarchical tag via chaining
    logger.io.net("connected")                  # dotted lower-case also works

Console filtering by tag is controlled via:
  - Env var:  TAGGIN_LOG_TAGS="QAT.*,io.net"   (# glob patterns)
              TAGGIN_LOG_TAGS="*"              (# ALL tags)
              TAGGIN_LOG_TAGS=""               (# hide all)
  - API:      set_visible_tags(["QAT.*", "TRAIN"]) or set_visible_tags(["*"])

Advanced:
  - TAGGIN_TAG_LEVEL (default INFO) controls the *default* level for tagged logs.
  - set_tag_level("QAT.FOLD", "DEBUG") to override a specific tag's level.
  - set_tag_rate_limit("TRAIN.BATCH", 0.25) limits a tag to once every 250ms.
  - Use `get_log_storage()` to save/search structured copies of every record.
"""
import fnmatch
import io
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Optional, Set, cast

# -----------------------------
# Progress-safe console support
# -----------------------------
_tqdm_write = None
try:  # pragma: no cover
    from tqdm import tqdm  # type: ignore
    _tqdm_write = tqdm.write
except Exception:  # pragma: no cover
    _tqdm_write = None

_alive_write = None
try:  # pragma: no cover
    from alive_progress.core.progress import print_over as _alive_write  # type: ignore
except Exception:  # pragma: no cover
    _alive_write = None


class ProgressSafeStreamHandler(logging.StreamHandler):
    """Console handler that won't break tqdm/alive_progress bars."""
    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - IO path
        try:
            msg = self.format(record)
            if _tqdm_write is not None:
                _tqdm_write(msg, file=self.stream)
            elif _alive_write is not None:
                _alive_write(msg, file=self.stream)
            else:
                self.stream.write(msg + ("" if msg.endswith("\n") else "\n"))
                self.flush()
        except Exception:
            self.handleError(record)


# -----------------------------
# Tag visibility / levels / rate limit
# -----------------------------
# None  -> show ALL tags on console
# set() -> hide ALL tags on console (default)
# set([...patterns...]) -> show tags matching any glob pattern
_ALLOWED_PATTERNS: Optional[Set[str]] = set()
_TAG_LEVEL: int = getattr(logging, os.getenv("TAGGIN_TAG_LEVEL", "INFO").upper(), logging.INFO)

# Per-tag level overrides (e.g., {"QAT.FOLD": logging.DEBUG})
_TAG_LEVEL_BY_NAME: dict[str, int] = {}

# Per-tag rate limiting: TAG -> (last_ts, min_interval_s)
_RATE_LIMITS: dict[str, tuple[float, float]] = {}

# Per-tag styling: tag -> TagStyle
_TAG_STYLE: dict[str, TagStyle] = {}

# Thread-safety for shared state
_TAG_LOCK = threading.RLock()

# Structured storage singleton
_STRUCTURED_STORAGE: Optional["LogStorage"] = None


def get_log_storage(create: bool = True) -> Optional["LogStorage"]:
    """Return the shared LogStorage (created on demand by default)."""
    global _STRUCTURED_STORAGE
    if _STRUCTURED_STORAGE is None and create:
        _STRUCTURED_STORAGE = LogStorage()
    return _STRUCTURED_STORAGE


def _parse_tags(spec: Optional[str]) -> Optional[Set[str]]:
    # None/empty -> hide all by default
    if spec is None:
        return set()
    s = spec.strip()
    if not s:
        return set()
    if s in {"*", "ALL", "all"}:
        return None
    parts = [p for p in re.split(r"[\s,]+", s) if p]
    # preserve case for patterns; matching is case-sensitive by choice
    return set(parts) or None


def set_visible_tags(tags: Iterable[str] | None) -> None:
    """Limit which tagged messages appear on stdout (glob patterns).

    - tags=None           → hide all tagged messages (default)
    - tags=["*"] / ["ALL"]→ show all tagged messages
    - tags=["PRUNE", "QAT.*", "io.net"] → only those patterns
    Un-tagged (normal) log records are unaffected by this filter.
    """
    global _ALLOWED_PATTERNS
    with _TAG_LOCK:
        if tags is None:
            _ALLOWED_PATTERNS = set()
            return
        t = list(tags)
        if len(t) == 1 and t[0] in ("*", "ALL", "all"):
            _ALLOWED_PATTERNS = None
        else:
            _ALLOWED_PATTERNS = {str(x) for x in t}


def get_visible_tags() -> Optional[Set[str]]:
    with _TAG_LOCK:
        return None if _ALLOWED_PATTERNS is None else set(_ALLOWED_PATTERNS)


def set_tag_level(tag: str, level: int | str) -> None:
    """Override the log level for a specific tag (exact match)."""
    lvl = getattr(logging, str(level).upper(), level)
    with _TAG_LOCK:
        _TAG_LEVEL_BY_NAME[str(tag)] = int(lvl)


def set_tag_rate_limit(tag: str, interval_s: float) -> None:
    """Rate-limit a tag to at most one message every `interval_s` seconds."""
    with _TAG_LOCK:
        _RATE_LIMITS[str(tag)] = (0.0, float(interval_s))


def set_tag_style(tag: str, color: str | None = None, emoji: str | None = None) -> None:
    """Define console color/emoji for a given tag (used when color output is enabled)."""
    with _TAG_LOCK:
        _TAG_STYLE[str(tag)] = TagStyle(color=color, emoji=emoji)


def _rate_ok(tag: str) -> bool:
    with _TAG_LOCK:
        last, interval = _RATE_LIMITS.get(tag, (0.0, 0.0))
        if interval <= 0:
            return True
        now = time.monotonic()
        if now - last >= interval:
            _RATE_LIMITS[tag] = (now, interval)
            return True
        return False


class _TagFilter(logging.Filter):
    """Filter: passes untagged records; restricts tagged records by _ALLOWED_PATTERNS."""
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        tag = getattr(record, "tag", None)
        if tag is None:
            return True  # normal logs pass; rely on level for console
        with _TAG_LOCK:
            pats = _ALLOWED_PATTERNS
        if pats is None:
            return True  # show all tags
        t = str(tag)
        return any(fnmatch.fnmatch(t, pat) for pat in pats)


# -----------------------------
# Formatters (console tag-first; file tag-aware)
# -----------------------------
class ConsoleTagFirstFormatter(logging.Formatter):
    """
    Console format:
      [TAG] message                 (for tagged logs)
      [ERROR] message               (untagged ERROR/CRITICAL)
      [WARNING] message             (untagged WARNING)
      message                       (untagged INFO)
      [DEBUG] message               (untagged DEBUG)
    """
    def __init__(self, *, enable_color: bool = False):
        super().__init__()
        self._enable_color = enable_color
        if enable_color:
            try:  # pragma: no cover - import guard
                import rich  # type: ignore
            except Exception:
                self._enable_color = False

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting
        msg = record.getMessage()
        tag = getattr(record, "tag", None)
        with _TAG_LOCK:
            tag_style = _TAG_STYLE.get(tag) if tag else None

        if self._enable_color:
            return self._format_rich(record, msg, tag, tag_style)

        return self._format_plain(record, msg, tag, tag_style)

    def _format_plain(self, record, msg, tag, tag_style) -> str:
        if tag:
            prefix = f"[{tag}]"
            if tag_style and tag_style.emoji:
                prefix = f"{tag_style.emoji} {prefix}"
            return f"{prefix} {msg}"
        if record.levelno >= logging.ERROR:
            return f"[ERROR] {msg}"
        if record.levelno >= logging.WARNING:
            return f"[WARNING] {msg}"
        if record.levelno < logging.INFO:
            return f"[DEBUG] {msg}"
        return msg

    def _format_rich(self, record, msg, tag, tag_style) -> str:
        from rich.console import Console  # type: ignore
        from rich.text import Text  # type: ignore

        text = Text()

        if tag:
            style = tag_style.color if tag_style else "bold cyan"
            label = f"[{tag}]"
            if tag_style and tag_style.emoji:
                label = f"{tag_style.emoji} {label}"
            text.append(label, style=style)
            text.append(" ")
            text.append(msg)
        else:
            style = None
            if record.levelno >= logging.ERROR:
                style = "bold red"
                prefix = "[ERROR]"
            elif record.levelno >= logging.WARNING:
                style = "yellow"
                prefix = "[WARNING]"
            elif record.levelno < logging.INFO:
                style = "dim"
                prefix = "[DEBUG]"
            else:
                prefix = ""

            if prefix:
                text.append(prefix, style=style)
                text.append(" ")
            text.append(msg)

        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True, color_system="auto")
        console.print(text, end="")
        return buffer.getvalue().rstrip("\n")

class TagStyle:
    """Stores optional color/emoji styling for tags."""
    __slots__ = ("color", "emoji")

    def __init__(self, color: str | None = None, emoji: str | None = None):
        self.color = color
        self.emoji = emoji


class FileTagAwareFormatter(logging.Formatter):
    """
    File format:
      2025-01-01 12:00:00 | INFO    | my.module | [TAG] message
      2025-01-01 12:00:00 | INFO    | my.module | message
    """
    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting
        # IMPORTANT: call super().format(record) so asctime and others are populated
        base = super().format(record)  # <- this sets asctime, formats the base fmt (no %(message)s in it)
        tag = getattr(record, "tag", None)
        msg = record.getMessage()
        if tag:
            return f"{base} | [{tag}] {msg}"
        return f"{base} | {msg}"


# -----------------------------
# Structured storage for saving/searching logs
# -----------------------------
@dataclass(frozen=True)
class StructuredLogEntry:
    timestamp: datetime
    level: str
    name: str
    tag: Optional[str]
    message: str


class LogStorage:
    """Thread-safe in-memory index backed by helper save/search methods."""
    def __init__(self) -> None:
        self._records: list[StructuredLogEntry] = []
        self._lock = threading.RLock()

    def add(self, entry: StructuredLogEntry) -> None:
        with self._lock:
            self._records.append(entry)

    def iter_records(self) -> list[StructuredLogEntry]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def save_text(self, path: str | Path, append: bool = False) -> Path:
        """Persist records as human-readable text while preserving timestamps."""
        entries = self.iter_records()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8") as fh:
            for entry in entries:
                tag = f"[{entry.tag}] " if entry.tag else ""
                line = (
                    f"{entry.timestamp.isoformat()} | "
                    f"{entry.level:<7} | "
                    f"{entry.name} | "
                    f"{tag}{entry.message}"
                )
                fh.write(line + "\n")
        return path

    def save_parquet(self, path: str | Path, append: bool = False) -> Path:
        """Persist records as a compact parquet file (requires pandas + pyarrow)."""
        try:
            import pandas as pd  # type: ignore
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "Saving to parquet requires pandas (and a parquet engine such as pyarrow)."
            ) from exc

        entries = self.iter_records()

        data = [
            {
                "timestamp": entry.timestamp,
                "level": entry.level,
                "name": entry.name,
                "tag": entry.tag,
                "message": entry.message,
            }
            for entry in entries
        ]
        df = pd.DataFrame(data)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if append and path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)
        df.to_parquet(path, index=False)
        return path

    def search_by_date(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[StructuredLogEntry]:
        """Return records whose timestamps fall within [start, end]."""
        entries = self.iter_records()
        result = []
        for entry in entries:
            if start and entry.timestamp < start:
                continue
            if end and entry.timestamp > end:
                continue
            result.append(entry)
        return result

    def search_by_tag(self, pattern: str) -> list[StructuredLogEntry]:
        """Return records whose tag matches the supplied glob pattern."""
        entries = self.iter_records()
        return [entry for entry in entries if entry.tag and fnmatch.fnmatch(entry.tag, pattern)]

    def search_fuzzy(
        self,
        text: str,
        *,
        threshold: float = 0.55,
        limit: int | None = None,
    ) -> list[StructuredLogEntry]:
        """Return records whose message roughly matches `text`."""
        entries = self.iter_records()
        scored: list[tuple[float, StructuredLogEntry]] = []
        for entry in entries:
            score = SequenceMatcher(None, entry.message, text).ratio()
            if score >= threshold:
                scored.append((score, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        matches = [entry for _, entry in scored]
        if limit is not None:
            return matches[:limit]
        return matches


class StructuredLogHandler(logging.Handler):
    """Handler that captures log records in a LogStorage index."""
    def __init__(self, storage: LogStorage):
        super().__init__(level=logging.NOTSET)
        self._storage = storage

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - thin wrapper
        msg = record.getMessage()
        entry = StructuredLogEntry(
            timestamp=datetime.fromtimestamp(record.created),
            level=record.levelname,
            name=record.name,
            tag=getattr(record, "tag", None),
            message=str(msg),
        )
        self._storage.add(entry)


def _ensure_structured_logging(logger: logging.Logger) -> Optional[LogStorage]:
    storage = get_log_storage(create=True)
    if storage is None:
        return None
    for handler in logger.handlers:
        if isinstance(handler, StructuredLogHandler):
            return storage
    logger.addHandler(StructuredLogHandler(storage))
    return storage


# -----------------------------
# Tagged logger implementation (with chaining via proxy)
# -----------------------------
def _emit_tag_log(logger: logging.Logger, tag: str, msg, *args, **kwargs) -> None:
    """Internal helper shared by TaggedLogger and shim."""
    # Rate limiting
    if not _rate_ok(tag):
        return
    # Level: per-tag override or default
    with _TAG_LOCK:
        lvl = _TAG_LEVEL_BY_NAME.get(tag, _TAG_LEVEL)
    # NOTE: do NOT prefix tag here. Formatters add tag where appropriate.
    logger.log(lvl, str(msg), *args, extra={"tag": tag}, **kwargs)


class _TagProxy:
    """
    Accumulates hierarchical tag parts via attribute access and emits on call.

    Example:
        log.QAT.FOLD("msg")  -> tag="QAT.FOLD"
        log.io.net("msg")    -> tag="io.net"
        log.QAT("msg")       -> tag="QAT"
    """
    __slots__ = ("_logger", "_parts")

    def __init__(self, logger: logging.Logger, parts: list[str]):
        self._logger = logger
        self._parts = parts

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return _TagProxy(self._logger, self._parts + [name])

    def __call__(self, msg, *args, **kwargs):
        tag = ".".join(self._parts)
        _emit_tag_log(self._logger, tag, msg, *args, **kwargs)


class TaggedLogger(logging.Logger):
    """Logger that treats unknown attributes as tag proxies (supports chaining)."""
    def __getattr__(self, name: str):  # pragma: no cover - dynamic method
        if name.startswith("_"):
            raise AttributeError(name)
        return _TagProxy(self, [name])


# -----------------------------
# Setup
# -----------------------------
def setup_logger(
    log_dir: str | Path = "logs",
    log_name: str = "run.log",
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    enable_color: bool = False,
) -> "TaggedLogger":
    """Create a root logger with file + console, plus dynamic tag support.

    - File handler: writes records ≥ file_level to <log_dir>/<log_name>.
      Tagged records are always written (no tag filtering).
    - Console handler: writes records ≥ console_level; additionally filters
      tagged messages by the tag allowlist (env TAGGIN_LOG_TAGS or set_visible_tags).
    """
    # install our dynamic-logger class for all subsequently created loggers
    try:
        logging.setLoggerClass(TaggedLogger)
    except Exception:
        pass

    # ensure even existing plain Logger instances support tag methods
    _install_tag_shim()

    # pick up tag allow-list from env if present (glob patterns)
    set_visible_tags(_parse_tags(os.getenv("TAGGIN_LOG_TAGS")))

    # convert strings to logging levels
    c_lvl = getattr(logging, console_level.upper(), logging.INFO)
    f_lvl = getattr(logging, file_level.upper(), logging.DEBUG)

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_path = Path(log_dir) / log_name

    logger = cast(TaggedLogger, logging.getLogger())  # root
    logger.setLevel(logging.DEBUG)  # capture EVERYTHING

    # If handlers already exist (e.g., notebooks), avoid duplicating
    if not logger.handlers:
        # ---- file handler ----
        fh = logging.FileHandler(log_path, mode="w")
        fh.setLevel(f_lvl)
        # This fmt is the "base" (date/level/name); tag & message are appended by FileTagAwareFormatter
        fh.setFormatter(
            FileTagAwareFormatter(
                fmt="%(asctime)s | %(levelname)-7s | %(name)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(fh)

        # ---- console handler (progress-safe, tag-first) ----
        ch = ProgressSafeStreamHandler()
        ch.setLevel(c_lvl)
        ch.setFormatter(ConsoleTagFirstFormatter(enable_color=enable_color))
        ch.addFilter(_TagFilter())
        logger.addHandler(ch)

    storage = _ensure_structured_logging(logger)
    logger.info(f"Logger started. Writing to {log_path}")
    visible = get_visible_tags()
    if visible is None:
        logger.info("Tag console filter: ALL")
    elif len(visible) == 0:
        logger.info("Tag console filter: HIDDEN (no tags)")
    else:
        logger.info(f"Tag console filter: {sorted(visible)}")
    if storage:
        logger.debug("Structured log capture enabled with %d historical entries.", len(storage.iter_records()))
    return logger


# Ensure modules importing this file get the dynamic logger behavior even if
# they never call setup_logger(). We avoid adding handlers automatically to not
# surprise libraries; setup_logger() remains the entry point for handlers.
try:  # pragma: no cover - safe best-effort
    logging.setLoggerClass(TaggedLogger)
except Exception:
    pass


def _install_tag_shim():  # pragma: no cover - straightforward shim
    """Monkey-patch logging.Logger with a dynamic tag method shim.

    This makes tagged calls like logger.MYTAG("msg") work even for
    already-created standard Logger instances (not just TaggedLogger).
    """
    if getattr(logging.Logger, "_taggin_tag_shim", False):
        return

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return _TagProxy(self, [name])

    logging.Logger.__getattr__ = __getattr__  # type: ignore[attr-defined]
    logging.Logger._taggin_tag_shim = True  # type: ignore[attr-defined]


# install the shim at import time too
_install_tag_shim()


if __name__ == "__main__":

    log: TaggedLogger = setup_logger(console_level="INFO", enable_color=True)

    # Hide all tags by default; enable just QAT.* and IO.net on console:
    set_visible_tags(["QAT.*", "IO.net", "RANDOM"])
    set_tag_level("QAT.FOLD", "DEBUG")

    set_tag_rate_limit("TRAIN.BATCH", 0.2)

    set_tag_style("QAT.FOLD", color="magenta", emoji="🧪")
    set_tag_style("IO.net", color="cyan", emoji="🌐")

    log.info("hello world (untagged always shows per level)")
    log.QAT("generic qat msg")             # hidden (matches filter, but INFO level)
    log.QAT.FOLD("folded %d layers", 12)   # using attribute chain still resolves to name "FOLD"

    log.RANDOM(f"Soem more info {12}")

    log.__getattr__("QAT.FOLD")("ok?")     # explicit (works)
    log.__getattr__("IO.net")("connected")

    storage = get_log_storage(create=False)
    if storage:
        storage.save_text("logs/demo_structured.log", append=False)
        try:
            storage.save_parquet("logs/demo_structured.parquet", append=False)
        except RuntimeError as exc:
            log.warning("Skipping parquet demo: %s", exc)

        log.info("Structured search results by tag QAT.* -> %d entries", len(storage.search_by_tag("QAT.*")))
        fuzzy = storage.search_fuzzy("connected", threshold=0.4)
        log.info("Fuzzy search for 'connected' -> %d entries", len(fuzzy))
