#pragma once

#include <cstddef>
#include <string>

namespace shared::tls {

// TLS-wraps an already-connected/-accepted fd in place: subsequent recv()/send() on that fd
// (called via this module, not raw ::recv/::send) transparently go through OpenSSL. Both take
// PEM paths; cafile empty means "don't verify the peer" (client: no chain check; server: don't
// request a client cert) - matches router_py's shared/ssl_utils.py, which trades hostname
// verification for simplicity since every cert here is a single self-signed file used as its own
// CA on both ends of a connection.
void wrap_client(int fd, const std::string& certfile, const std::string& keyfile,
                  const std::string& cafile, const std::string& host);
void wrap_server(int fd, const std::string& certfile, const std::string& keyfile,
                  const std::string& cafile);

bool is_tls(int fd);

// Fall through to plain ::recv/::send when fd isn't registered - lets framing.cpp/ims_connect.cpp
// call these unconditionally regardless of whether ssl_active is set for a given connection.
ssize_t recv(int fd, void* buf, size_t len);
ssize_t send(int fd, const void* buf, size_t len);

// SSL_shutdown + SSL_free + drop from the registry. Idempotent. Callers still separately
// ::shutdown()/::close() the fd itself - this only releases the TLS state associated with it.
void close(int fd);

}  // namespace shared::tls
