package com.xv6.shared;

import java.util.logging.Level;

/** Maps Python-style level names (DEBUG/INFO/WARNING/ERROR) to java.util.logging Levels. */
public final class LogLevels {

    private LogLevels() {
    }

    public static Level parse(String name) {
        return switch (name.toUpperCase()) {
            case "DEBUG" -> Level.FINE;
            case "WARNING", "WARN" -> Level.WARNING;
            case "ERROR" -> Level.SEVERE;
            default -> Level.INFO;
        };
    }

    public static String toPythonName(Level level) {
        if (level.equals(Level.FINE) || level.equals(Level.FINER) || level.equals(Level.FINEST)) {
            return "DEBUG";
        }
        if (level.equals(Level.WARNING)) {
            return "WARNING";
        }
        if (level.equals(Level.SEVERE)) {
            return "ERROR";
        }
        return "INFO";
    }
}
