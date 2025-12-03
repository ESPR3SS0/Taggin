## Taggin

### Welcome

Taggin is a tiny layer on top of the Python stdlib logger that treats
attribute access as dynamic tags (`log.TRAIN.BATCH("...")`). Tags can be
filtered via glob patterns, assigned custom log levels, rate limited, and every
log is mirrored into a structured store that can be searched or exported.

### Installation

Install via pip (or pixi/uv) with:

```bash
pip install taggin
```

The CLI depends on `arrow` and `cyclopts` (included), colorful console output
uses `rich`, and saving/reading Parquet requires `pandas` plus a backend such as
`pyarrow` or `fastparquet`.

### Usage

#### Quick start

```python
from datetime import datetime
from taggin import (
    setup_logger,
    get_log_storage,
    set_visible_tags,
    set_tag_style,
)

log = setup_logger(enable_color=True)  # enables Rich-powered colors where supported
set_visible_tags(["TRAIN.*", "io.net"])
set_tag_style("TRAIN.START", color="green", emoji="🚂")

log.info("Booting")
log.TRAIN.START("epoch=%s", 1)
log.io.net("connected to redis")

storage = get_log_storage()
storage.save_text("logs/run.txt")                # new file
storage.save_text("logs/run.txt", append=True)   # append to existing file
storage.save_parquet("logs/run.parquet")         # requires pandas + pyarrow

recent = storage.search_by_date(start=datetime.utcnow().replace(hour=0, minute=0))
by_tag = storage.search_by_tag("TRAIN.*")
approx = storage.search_fuzzy("redis connection failed", threshold=0.5)
```

When `enable_color=True`, tags render in color (and can add emoji via
`set_tag_style`). Disable the flag to fall back to plain text.

All structured entries store the timestamp, level, logger name, tag, and message
so they remain queryable even if the original message contains its own time or
date. This makes ad-hoc debugging easy whether you prefer grepping the text
artifact or using a DataFrame/Parquet workflow.

#### CLI search utility

A small `cyclopts`-powered CLI is available for exploring saved logs without
writing Python. Assuming you saved either a structured text log or Parquet file:

```bash
taggin by-tag logs/run.txt "TRAIN.*"
taggin by-date logs/run.parquet --start "2025-01-01" --end "2025-01-05"
taggin fuzzy logs/run.txt "redis timeout" --threshold 0.4 --limit 5
taggin tags logs/run.txt                    # list all known tags
taggin by-tag logs/run.txt "TRAIN.*" --json-output   # machine-friendly
```

Each command prints matching entries in the same concise `[TAG] message` style,
or JSON (when `--json-output` is provided) for downstream scripting.

#### Tests

Run the small pytest suite (which also exercises the Parquet writer when pandas
is available) with:

```bash
pytest
```

#### Documentation

This repo ships MkDocs docs (Home, Examples, API Reference). Preview locally:

```bash
mkdocs serve
```

or build static files via `mkdocs build`. The content lives under `docs/`.
