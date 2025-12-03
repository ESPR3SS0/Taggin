# Examples

## Training Pipeline

```python
from taggin import setup_logger, set_visible_tags, get_log_storage

log = setup_logger()
set_visible_tags(["TRAIN.*", "DATA.*"])

log.DATA.LOAD("rows=%d", 12_345)
log.TRAIN.START("epoch=%s lr=%.4f", 1, 0.0003)

for step in range(3):
    log.TRAIN.BATCH("step=%d loss=%.3f", step, 0.1 * step)

log.TRAIN.END("epoch=%s acc=%.2f", 1, 0.92)

storage = get_log_storage()
storage.save_text("logs/train.txt")
```

### Tag visibility quick check

```python
from taggin import setup_logger, set_visible_tags

log = setup_logger()

set_visible_tags([])       # hide all tagged messages on console
log.TRAIN.START("hidden")  # still written to file / storage

set_visible_tags(["*"])    # show every tag on console
log.TRAIN.START("visible")
```

The first call suppresses tagged output entirely (console stays quiet), while
the second emits `[TRAIN.START] visible` to stdout; both records are still
captured in the log file and structured storage.

## Rate Limiting and Levels

```python
from taggin import setup_logger, set_tag_rate_limit, set_tag_level, set_tag_style

log = setup_logger(enable_color=True)
set_tag_rate_limit("METRIC.BATCH", 0.5)      # throttle noisy metrics
set_tag_level("ALERT.CRIT", "WARNING")       # bump level so it hits console
set_tag_style("ALERT.CRIT", color="bold red", emoji="🚨")

log.METRIC.BATCH("loss=%f", 0.1)
log.METRIC.BATCH("loss=%f", 0.2)             # skipped (rate limited)
log.ALERT.CRIT("model diverged")
```

## CLI Recipes

Once you have a structured log text file or Parquet dump, slice it with the CLI:

```bash
# Show only IO.* events
taggin by-tag logs/run.txt "IO.*"

# Inspect a specific window (inclusive)
taggin by-date logs/run.txt --start "2025-01-05T10:00:00" --end "2025-01-05T11:00:00"

# Fuzzy search for "timeout" and export JSON
taggin fuzzy logs/run.txt timeout --threshold 0.3 --json-output > timeout.json

# List every tag contained in the file
taggin tags logs/run.txt --json-output
```
