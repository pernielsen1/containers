import ssl


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
