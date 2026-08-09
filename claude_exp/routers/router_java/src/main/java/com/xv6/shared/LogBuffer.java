package com.xv6.shared;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.logging.Handler;
import java.util.logging.LogRecord;

/**
 * Captures the last N log lines in a deque. Installed on the root logger by CommandServer. Port
 * of router_py's shared/log_buffer.py, using java.util.logging (built into the JDK, no extra
 * dependency) in place of Python's logging module.
 */
public final class LogBuffer extends Handler {

    private final int maxLen;
    private final Deque<String> lines = new ArrayDeque<>();

    public LogBuffer(int maxLen) {
        this.maxLen = maxLen;
        setFormatter(new JsonLogFormatter());
    }

    @Override
    public synchronized void publish(LogRecord record) {
        try {
            lines.addLast(getFormatter().format(record).stripTrailing());
            while (lines.size() > maxLen) {
                lines.pollFirst();
            }
        } catch (Exception ignored) {
            // Mirrors Python's LogBuffer.emit: never let a formatting failure break logging.
        }
    }

    public synchronized List<String> getLines() {
        return new ArrayList<>(lines);
    }

    @Override
    public void flush() {
    }

    @Override
    public void close() {
    }
}
