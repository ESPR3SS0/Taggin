# API Reference

## Module `taggin.log`

### `setup_logger(log_dir="logs", log_name="run.log", console_level="INFO", file_level="DEBUG", enable_color=False)`
Creates a root logger with file + console handlers, installs the tagged logger
class, applies tag filters, and attaches a structured capture handler. Returns
the configured root logger. Set `enable_color=True` to opt into Rich-powered
colored console output (respects `set_tag_style` customization).

Parameters at a glance:

- `log_dir` / `log_name` – where the file handler writes (default: `logs/run.log`).
- `console_level` – minimum level for the console handler; tags are additionally
  filtered by `set_visible_tags` / `TAGGIN_LOG_TAGS`.
- `file_level` – minimum level for the file handler. Tagged messages bypass the
  console filter but do respect this file threshold.
- `enable_color` – toggle Rich-based styling for tagged messages (honors
  `set_tag_style`). Leave `False` to keep plain output.

Environment helpers:

- `TAGGIN_LOG_TAGS="*"` – show all tags on console; comma/space-separated globs
  like `TAGGIN_LOG_TAGS="TRAIN.* io.*"` are also supported.
- `TAGGIN_TAG_LEVEL="DEBUG"` – default level for tag calls (overrides INFO).

### `set_visible_tags(tags)`
Limit which tagged records appear on the console. Accepts `None`, `["*"]`, or
a list of glob patterns like `["TRAIN.*", "io.net"]`.

Pass `None`/`[]`/`set()` to hide all tagged records from the console while still
capturing them in the log file and structured store. Use `["*"]` or
`["ALL"]`/`["all"]` to show everything.

### `set_tag_level(tag, level)`
Override the log level for a specific tag (`level` can be a string or numeric).

### `set_tag_rate_limit(tag, interval_s)`
Throttle a tag so it emits at most once every `interval_s` seconds.

### `set_tag_style(tag, color=None, emoji=None)`
Define the console color and optional emoji prefix for a tag. Takes effect when
`setup_logger(enable_color=True)` is used; emoji (when provided) also appears in
plain output.

### `get_log_storage(create=True)`
Returns the shared `LogStorage` instance that mirrors all records. When
`create=False`, returns `None` if structured capture was never initialized.

### `LogStorage`
- `add(entry)` – manually append a `StructuredLogEntry`.
- `iter_records()` – returns a copy of stored entries.
- `clear()` – empties the storage.
- `save_text(path, append=False)` – write entries to text file.
- `save_parquet(path, append=False)` – write entries to Parquet (pandas + pyarrow).
- `search_by_date(start=None, end=None)` – filter by timestamps.
- `search_by_tag(pattern)` – glob match tags.
- `search_fuzzy(text, threshold=0.55, limit=None)` – approximate message search.

`LogStorage.save_text` produces lines in the same format consumed by the CLI,
making it easy to round-trip logs between Python and shell usage. Parquet saves
preserve native datetimes for DataFrame-heavy workflows.

### `StructuredLogEntry`
Immutable data class with fields `timestamp`, `level`, `name`, `tag`, and
`message`.

### Tagged Logger
All `logging.Logger` instances gain dynamic tag attributes. Examples:

```python
log = setup_logger()
log.TRAIN.START("epoch=%s", 1)
log.io.net("connected")
log.QAT.FOLD("folded layers")
```

## Module `taggin.cli`

The CLI is built with Cyclopts and exposes three commands:

- `by-date PATH [--start ISO] [--end ISO] [--json-output]`
- `by-tag PATH PATTERN [--json-output]`
- `fuzzy PATH TEXT [--threshold 0.55] [--limit N] [--json-output]`
- `tags PATH [--json-output]`

Each command loads either a structured text log or Parquet file, runs the
corresponding `LogStorage` search, and prints results.

JSON output format (shared by `by-date`, `by-tag`, `fuzzy`):

```json
[
  {
    "timestamp": "2025-01-05T10:00:01.234567",
    "level": "INFO",
    "name": "my.module",
    "tag": "TRAIN.EPOCH",
    "message": "epoch=1 acc=0.92"
  }
]
```

`tags` without `--json-output` renders a frequency-sorted table; with
`--json-output` it returns an array of `{ "tag": "...", "count": 123 }` pairs
for scripting.
