import ssl

# OpenSSL alert/reason substrings that specifically indicate a certificate problem (wrong CA,
# expired cert, hostname mismatch, peer rejected our cert, ...) as opposed to a handshake that
# simply never completed (a stray probe, a client abandoning a slow/retried connection attempt, an
# ordinary network hiccup) - see is_cert_desync_error().
_CERT_REASON_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED",
    "CERTIFICATE_EXPIRED",
    "CERTIFICATE_UNKNOWN",
    "CERTIFICATE_REQUIRED",
    "UNKNOWN_CA",
    "BAD_CERTIFICATE",
    "SELF_SIGNED_CERT",
    "UNABLE_TO_GET_ISSUER_CERT",
)


def is_cert_desync_error(exc: ssl.SSLError) -> bool:
    """True only for SSL errors that actually indicate mismatched/untrusted certificates -
    something a human needs to fix, since retrying won't help. False for everything else
    ssl.SSLError covers: SSLEOFError (the peer's TCP connection dropped mid-handshake - a stray
    probe, a client reconnecting too fast, ordinary connectivity flapping under chaos testing)
    and SSLZeroReturnError (a clean TLS-level shutdown) are common and are NOT cert problems.
    Confirmed live under chaos_monkey.py: an upstream_1 reconnect race produced exactly an
    SSLEOFError ("UNEXPECTED_EOF_WHILE_READING") with no cert issue at all - misclassifying that
    as ERROR/"needs manual intervention" would be a false alarm on every routine reconnect race,
    not just a real desync.
    """
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    if isinstance(exc, (ssl.SSLEOFError, ssl.SSLZeroReturnError)):
        return False
    reason = getattr(exc, "reason", None) or ""
    return any(marker in reason for marker in _CERT_REASON_MARKERS)


def build_client_context(certfile=None, keyfile=None, cafile=None):
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    context.check_hostname = False
    if cafile:
        context.load_verify_locations(cafile=cafile)
    if certfile and keyfile:
        context.load_cert_chain(certfile, keyfile)
    return context


def build_server_context(certfile, keyfile, cafile=None):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile, keyfile)
    if cafile:
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cafile=cafile)
    return context


def wrap_client_socket(sock, *, ssl_active, certfile=None, keyfile=None, cafile=None, server_hostname=None):
    if not ssl_active:
        return sock
    context = build_client_context(certfile=certfile, keyfile=keyfile, cafile=cafile)
    return context.wrap_socket(sock, server_hostname=server_hostname or "localhost")


def wrap_server_socket(sock, *, ssl_active, certfile, keyfile, cafile=None):
    if not ssl_active:
        return sock
    context = build_server_context(certfile, keyfile, cafile=cafile)
    return context.wrap_socket(sock, server_side=True)
