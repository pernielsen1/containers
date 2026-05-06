import collections
import logging


class LogBuffer(logging.Handler):
    def __init__(self, maxlen=2000):
        super().__init__()
        self._lines = collections.deque(maxlen=maxlen)

    def emit(self, record):
        try:
            self._lines.append(self.format(record))
        except Exception:
            self.handleError(record)

    def get_lines(self):
        return list(self._lines)
