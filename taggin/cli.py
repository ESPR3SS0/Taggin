"""
Command-line helpers for searching Taggin structured logs.

Usage examples:
    python -m taggin.cli by-tag logs/demo_structured.log "QAT.*"
    python -m taggin.cli by-date logs/demo_structured.parquet --start "2025-01-01"
    python -m taggin.cli fuzzy logs/demo_structured.log "redis" --limit 5
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional
from rich.console import Console

import arrow
from cyclopts import App

from .log import LogStorage, StructuredLogEntry

app = App(name="taggin")
console = Console()


def _format_entry(entry: StructuredLogEntry) -> str:
    tag = f"[{entry.tag}] " if entry.tag else ""
    return (
        f"{entry.timestamp.isoformat()} | "
        f"{entry.level:<7} | "
        f"{entry.name} | "
        f"{tag}{entry.message}"
    )


def _load_entries(path: Path) -> Iterable[StructuredLogEntry]:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        yield from _load_from_parquet(path)
    else:
        yield from _load_from_text(path)


def _load_from_text(path: Path) -> Iterable[StructuredLogEntry]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" | ", 3)
            if len(parts) != 4:
                continue
            ts_str, level, name, rest = parts
            timestamp = arrow.get(ts_str).naive
            tag: Optional[str] = None
            message = rest
            if rest.startswith("[") and "] " in rest:
                closing = rest.find("]")
                if closing != -1 and len(rest) > closing + 1:
                    tag = rest[1:closing]
                    message = rest[closing + 2 :]
            yield StructuredLogEntry(
                timestamp=timestamp,
                level=level.strip(),
                name=name.strip(),
                tag=tag,
                message=message,
            )


def _load_from_parquet(path: Path) -> Iterable[StructuredLogEntry]:
    try:
        import pandas as pd  # type: ignore
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "Reading parquet logs requires pandas (and a parquet backend such as pyarrow)."
        ) from exc
    df = pd.read_parquet(path)
    for row in df.to_dict("records"):
        timestamp = row["timestamp"]
        if hasattr(timestamp, "to_pydatetime"):
            timestamp = timestamp.to_pydatetime()
        yield StructuredLogEntry(
            timestamp=timestamp,
            level=row["level"],
            name=row["name"],
            tag=row.get("tag"),
            message=row["message"],
        )


def _load_storage(path: Path) -> LogStorage:
    storage = LogStorage()
    for entry in _load_entries(path):
        storage.add(entry)
    return storage


def _parse_datetime(value: Optional[str]):
    if value is None:
        return None
    return arrow.get(value).naive


def _print_results(
    entries: Iterable[StructuredLogEntry],
    *,
    as_json: bool = False,
) -> None:
    entries = list(entries)
    if len(entries) == 0:
        console.print("No entries found!")
        return

    if as_json:

        import json

        output = [
            {
                "timestamp": entry.timestamp.isoformat(),
                "level": entry.level,
                "name": entry.name,
                "tag": entry.tag,
                "message": entry.message,
            }
            for entry in entries
        ]
        print(json.dumps(output, indent=2))
        return

    for entry in entries:
        print(_format_entry(entry))

    return


@app.command()
def by_date(
    path: Path,
    start: str | None = None,
    end: str | None = None,
    json_output: bool = False,
) -> None:
    """Search logs by inclusive datetime range."""
    storage = _load_storage(path)
    hits = storage.search_by_date(start=_parse_datetime(start), end=_parse_datetime(end))
    _print_results(hits, as_json=json_output)


@app.command()
def by_tag(path: Path, pattern: str, json_output: bool = False) -> None:
    """Search logs by tag glob pattern (e.g., TRAIN.*, io.*)."""
    storage = _load_storage(path)
    hits = storage.search_by_tag(pattern)
    _print_results(hits, as_json=json_output)


@app.command()
def fuzzy(
    path: Path,
    text: str,
    threshold: float = 0.55,
    limit: int | None = None,
    json_output: bool = False,
) -> None:
    """Search logs by fuzzy message matching."""
    storage = _load_storage(path)
    hits = storage.search_fuzzy(text, threshold=threshold, limit=limit)
    _print_results(hits, as_json=json_output)


@app.command()
def tags(path: Path, json_output: bool = False) -> None:
    """List all unique tags stored in the log file (text or parquet)."""
    storage = _load_storage(path)
    entries = storage.iter_records()
    tag_set = sorted({entry.tag for entry in entries if entry.tag})
    if json_output:
        import json
        print(json.dumps(tag_set, indent=2))
    else:
        for tag in tag_set:
            print(tag)

def main() -> None:
    app()


if __name__ == "__main__":
    main()
