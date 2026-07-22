package com.xv6.shared;

/** Adapter record for {@link Framing}, mirroring xv5's router/config.py Framing.to_dict(). */
public record FramingConfig(
        String headerHex,
        String lengthFieldType,
        int lengthFieldBytes,
        int maxMessageBytes) {

    public FramingConfig(String headerHex, String lengthFieldType, int lengthFieldBytes) {
        this(headerHex, lengthFieldType, lengthFieldBytes, Framing.DEFAULT_MAX_MESSAGE_BYTES);
    }
}
