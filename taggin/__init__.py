"""Taggin package: tagged logging helpers and CLI tools."""

from .log import (
    FileTagAwareFormatter,
    LogStorage,
    ProgressSafeStreamHandler,
    StructuredLogEntry,
    TaggedLogger,
    ConsoleTagFirstFormatter,
    get_log_storage,
    set_tag_level,
    set_tag_rate_limit,
    set_tag_style,
    set_visible_tags,
    setup_logger,
)

__all__ = [
    "ConsoleTagFirstFormatter",
    "FileTagAwareFormatter",
    "LogStorage",
    "ProgressSafeStreamHandler",
    "StructuredLogEntry",
    "TaggedLogger",
    "get_log_storage",
    "set_tag_level",
    "set_tag_rate_limit",
    "set_tag_style",
    "set_visible_tags",
    "setup_logger",
]
