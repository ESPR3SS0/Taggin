# API Reference

## Module `taggin.log`

### `setup_logger(log_dir="logs", log_name="run.log", console_level="INFO", file_level="DEBUG", enable_color=False)`
Creates a root logger with file + console handlers, installs the tagged logger
class, applies tag filters, and attaches a structured capture handler. Returns
the configured root logger. Set `enable_color=True` to opt into Rich-powered
colored console output (respects `set_tag_style` customization).

### `set_visible_tags(tags)`
Limit which tagged records appear on the console. Accepts `None`, `["*"]`, or
a list of glob patterns like `["TRAIN.*", "io.net"]`.

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
