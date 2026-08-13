package com.router.shared;

/** Adapter record for {@link Framing}, mirroring router_py's router/config.py Framing.to_dict(). */
public record FramingConfig(
        String headerHex,
        String lengthFieldType,
        int lengthFieldBytes,
        int maxMessageBytes) {

    public FramingConfig(String headerHex, String lengthFieldType, int lengthFieldBytes) {
        this(headerHex, lengthFieldType, lengthFieldBytes, Framing.DEFAULT_MAX_MESSAGE_BYTES);
    }
}
