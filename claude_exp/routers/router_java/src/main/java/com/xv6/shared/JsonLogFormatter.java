package com.xv6.shared;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.logging.Formatter;
import java.util.logging.LogRecord;

/**
 * One JSON object per log line, matching router_py's shared/json_log.py JsonFormatter shape
 * ({ts, level, logger, message}[, exc_info]) - same shape on stdout and on the /logs ring
 * buffer, so either can be piped into jq or diffed against another actor's log.
 */
public final class JsonLogFormatter extends Formatter {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Override
    public String format(LogRecord record) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("ts", Instant.ofEpochMilli(record.getMillis()).toString());
        entry.put("level", LogLevels.toPythonName(record.getLevel()));
        entry.put("logger", record.getLoggerName());
        entry.put("message", formatMessage(record));
        if (record.getThrown() != null) {
            StringWriter sw = new StringWriter();
            record.getThrown().printStackTrace(new PrintWriter(sw));
            entry.put("exc_info", sw.toString());
        }
        try {
            return MAPPER.writeValueAsString(entry) + System.lineSeparator();
        } catch (Exception e) {
            return "{\"level\":\"ERROR\",\"message\":\"log formatting failed\"}" + System.lineSeparator();
        }
    }
}
