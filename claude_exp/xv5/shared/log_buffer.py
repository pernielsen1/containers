import logging
from collections import deque


class LogBuffer(logging.Handler):
    """Captures last N log lines in a deque. Installed on root logger by CommandServer."""

    def __init__(self, maxlen: int = 2000):
        super().__init__()
        self._lines = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._lines.append(self.format(record))
        except Exception:
            pass

    def get_lines(self) -> list:
        return list(self._lines)
