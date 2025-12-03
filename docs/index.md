# Taggin

Taggin is a tiny layer atop Python's stdlib logger that lets you treat method
access as dynamic tags while mirroring every record into a searchable store.
Use attribute access such as `log.TRAIN.BATCH("...")`, filter by glob patterns,
rate-limit noisy categories, and export the captured history to text or Parquet
for lightweight analytics.

## Features

- **Magic tags** – any attribute chain on a logger becomes a structured tag.
- **Structured storage** – every record (timestamp, level, name, tag, message)
  is retained in-memory for later saving or searching.
- **CLI explorer** – the `taggin` CLI (built with Cyclopts) supports date,
  tag, and fuzzy searches with optional JSON output.
- **Progress-safe console handler** – won't break tqdm/alive-progress bars.
- **Optional color + emoji** – enable Rich-driven styling via
  `setup_logger(enable_color=True)` and `set_tag_style`.

## Quick Start

```python
from datetime import datetime
from taggin import (
    setup_logger,
    set_visible_tags,
    get_log_storage,
    set_tag_style,
)

log = setup_logger(console_level="INFO", enable_color=True)
set_visible_tags(["TRAIN.*", "io.net"])
set_tag_style("TRAIN.START", color="green", emoji="🚂")

log.info("Booting system")
log.TRAIN.START("epoch=%s", 1)
log.io.net("connected to redis")

storage = get_log_storage()
storage.save_text("logs/run.txt")
storage.save_parquet("logs/run.parquet")  # requires pandas + pyarrow

recent = storage.search_by_date(start=datetime.utcnow().replace(hour=0, minute=0))
train = storage.search_by_tag("TRAIN.*")
issues = storage.search_fuzzy("redis timeout", threshold=0.5)
```

Set `enable_color=False` (default) to keep plain console output.

## CLI Search

```bash
taggin by-tag logs/run.txt "TRAIN.*"
taggin by-date logs/run.parquet --start "2025-01-01" --end "2025-01-05"
taggin fuzzy logs/run.txt "redis timeout" --threshold 0.4 --limit 5 --json-output
taggin tags logs/run.txt
```

Each command prints human-readable text or JSON (`--json-output`) for downstream
automation.

## Installation & Development

```bash
pip install taggin
pytest  # run the tests
mkdocs serve  # preview docs
```
