package com.xv6.shared;

import java.nio.charset.Charset;

/** EBCDIC 500 charset (Python's "cp500"), used for the IMS Connect wire protocol. */
final class Charset500 {
    static final Charset CHARSET = Charset.forName("Cp500");

    private Charset500() {
    }
}
