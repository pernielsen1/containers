#include "shared/tls.h"

#include <sys/socket.h>

#include <cerrno>
#include <mutex>
#include <stdexcept>
#include <unordered_map>

#include <openssl/err.h>
#include <openssl/ssl.h>

namespace shared::tls {

namespace {

std::mutex g_mutex;
std::unordered_map<int, SSL*> g_registry;

std::string openssl_error() {
    unsigned long code = ERR_get_error();
    char buf[256];
    ERR_error_string_n(code, buf, sizeof(buf));
    return std::string(buf);
}

SSL* lookup(int fd) {
    std::lock_guard<std::mutex> lock(g_mutex);
    auto it = g_registry.find(fd);
    return it == g_registry.end() ? nullptr : it->second;
}

void register_fd(int fd, SSL* ssl) {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_registry[fd] = ssl;
}

}  // namespace

void wrap_client(int fd, const std::string& certfile, const std::string& keyfile,
                  const std::string& cafile, const std::string& host) {
    SSL_CTX* ctx = SSL_CTX_new(TLS_client_method());
    if (!ctx) throw std::runtime_error("SSL_CTX_new failed: " + openssl_error());

    if (!cafile.empty()) {
        if (SSL_CTX_load_verify_locations(ctx, cafile.c_str(), nullptr) != 1) {
            SSL_CTX_free(ctx);
            throw std::runtime_error("failed to load CA file " + cafile + ": " + openssl_error());
        }
        SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER, nullptr);
    } else {
        SSL_CTX_set_verify(ctx, SSL_VERIFY_NONE, nullptr);
    }
    if (!certfile.empty() && !keyfile.empty()) {
        if (SSL_CTX_use_certificate_file(ctx, certfile.c_str(), SSL_FILETYPE_PEM) != 1 ||
            SSL_CTX_use_PrivateKey_file(ctx, keyfile.c_str(), SSL_FILETYPE_PEM) != 1) {
            SSL_CTX_free(ctx);
            throw std::runtime_error("failed to load client cert/key: " + openssl_error());
        }
    }

    SSL* ssl = SSL_new(ctx);
    SSL_CTX_free(ctx);  // SSL_new() already bumped ctx's refcount; ssl keeps it alive.
    if (!ssl) throw std::runtime_error("SSL_new failed: " + openssl_error());

    if (!host.empty()) SSL_set_tlsext_host_name(ssl, host.c_str());
    SSL_set_fd(ssl, fd);

    if (SSL_connect(ssl) != 1) {
        std::string err = openssl_error();
        SSL_free(ssl);
        throw std::runtime_error("SSL_connect failed: " + err);
    }

    register_fd(fd, ssl);
}

void wrap_server(int fd, const std::string& certfile, const std::string& keyfile,
                  const std::string& cafile) {
    SSL_CTX* ctx = SSL_CTX_new(TLS_server_method());
    if (!ctx) throw std::runtime_error("SSL_CTX_new failed: " + openssl_error());

    if (SSL_CTX_use_certificate_file(ctx, certfile.c_str(), SSL_FILETYPE_PEM) != 1 ||
        SSL_CTX_use_PrivateKey_file(ctx, keyfile.c_str(), SSL_FILETYPE_PEM) != 1) {
        SSL_CTX_free(ctx);
        throw std::runtime_error("failed to load server cert/key: " + openssl_error());
    }
    // A cafile here means mutual TLS: require and verify a client cert against it - matches
    // router_py's build_server_context, where the same self-signed file doubles as CA.
    if (!cafile.empty()) {
        if (SSL_CTX_load_verify_locations(ctx, cafile.c_str(), nullptr) != 1) {
            SSL_CTX_free(ctx);
            throw std::runtime_error("failed to load CA file " + cafile + ": " + openssl_error());
        }
        SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER | SSL_VERIFY_FAIL_IF_NO_PEER_CERT, nullptr);
    }

    SSL* ssl = SSL_new(ctx);
    SSL_CTX_free(ctx);
    if (!ssl) throw std::runtime_error("SSL_new failed: " + openssl_error());

    SSL_set_fd(ssl, fd);
    if (SSL_accept(ssl) != 1) {
        std::string err = openssl_error();
        SSL_free(ssl);
        throw std::runtime_error("SSL_accept failed: " + err);
    }

    register_fd(fd, ssl);
}

bool is_tls(int fd) { return lookup(fd) != nullptr; }

ssize_t recv(int fd, void* buf, size_t len) {
    SSL* ssl = lookup(fd);
    if (!ssl) return ::recv(fd, buf, len, 0);

    int rc = SSL_read(ssl, buf, static_cast<int>(len));
    if (rc > 0) return rc;

    int err = SSL_get_error(ssl, rc);
    if (err == SSL_ERROR_ZERO_RETURN) return 0;  // clean TLS close_notify: treat as EOF
    if (err != SSL_ERROR_SYSCALL) errno = EIO;   // SYSCALL: errno (e.g. EINTR) is already set
    return -1;
}

ssize_t send(int fd, const void* buf, size_t len) {
    SSL* ssl = lookup(fd);
    if (!ssl) return ::send(fd, buf, len, MSG_NOSIGNAL);

    int rc = SSL_write(ssl, buf, static_cast<int>(len));
    if (rc > 0) return rc;

    int err = SSL_get_error(ssl, rc);
    if (err != SSL_ERROR_SYSCALL) errno = EIO;
    return -1;
}

void close(int fd) {
    SSL* ssl = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        auto it = g_registry.find(fd);
        if (it == g_registry.end()) return;
        ssl = it->second;
        g_registry.erase(it);
    }
    SSL_shutdown(ssl);
    SSL_free(ssl);
}

}  // namespace shared::tls
