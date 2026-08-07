import json
import logging
import sys
from datetime import datetime, timezone

# Fields pulled out of LogRecord.__dict__ (via logging's `extra=`) into top-level JSON keys when
# present, rather than left buried in the message string - lets /logs and stdout both be
# grep/jq-able on the correlation ID that joins a transaction across actors.
_EXTRA_FIELDS = ("router_stan",)


class JsonFormatter(logging.Formatter):
    """One JSON object per log line. Same shape on stdout and on the /logs ring buffer, so
    either can be piped into jq or diffed against another actor's log on router_stan."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = value
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level=logging.INFO) -> None:
    """Replaces the old logging.basicConfig(format="...") call at each actor's entry point.
    Uses basicConfig under the hood so it keeps the same idempotency (a no-op if the root
    logger already has handlers, e.g. under pytest)."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler])
