package com.router.shared;

import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLServerSocket;
import javax.net.ssl.SSLServerSocketFactory;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManagerFactory;
import java.io.IOException;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.Base64;

/**
 * Minimal PEM-based TLS wiring for raw sockets and HTTP(S), no extra dependency beyond the JDK's
 * own javax.net.ssl - mirrors router_py's shared/ssl_utils.py and router_cpp's shared/tls.cpp: a
 * single self-signed cert doubles as both this actor's identity and the CA it trusts its peer
 * against (mutual TLS whenever a cafile is configured). Private keys must be PKCS8 PEM
 * (create_certificate.py writes that format) - the JDK has no built-in parser for the older
 * PKCS1/"TraditionalOpenSSL" format OpenSSL itself defaults to, and pulling in BouncyCastle just
 * for that felt like the wrong tradeoff given Python/C++ read PKCS8 identically via OpenSSL.
 */
public final class SslUtils {

    private SslUtils() {
    }

    private static X509Certificate loadCertificate(String pemPath) throws IOException {
        try (var in = Files.newInputStream(Path.of(pemPath))) {
            return (X509Certificate) CertificateFactory.getInstance("X.509").generateCertificate(in);
        } catch (java.security.cert.CertificateException e) {
            throw new IOException("failed to parse certificate " + pemPath, e);
        }
    }

    private static PrivateKey loadPrivateKey(String pemPath) throws IOException {
        String pem = Files.readString(Path.of(pemPath));
        String base64 = pem.replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replaceAll("\\s", "");
        byte[] der = Base64.getDecoder().decode(base64);
        try {
            return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(der));
        } catch (Exception e) {
            throw new IOException("failed to parse private key " + pemPath, e);
        }
    }

    private static SSLContext buildContext(String certfile, String keyfile, String cafile) throws IOException {
        try {
            KeyManagerFactory kmf = null;
            if (certfile != null && keyfile != null) {
                KeyStore keyStore = KeyStore.getInstance("PKCS12");
                keyStore.load(null, null);
                keyStore.setKeyEntry("identity", loadPrivateKey(keyfile), new char[0],
                        new Certificate[]{loadCertificate(certfile)});
                kmf = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
                kmf.init(keyStore, new char[0]);
            }

            TrustManagerFactory tmf = null;
            if (cafile != null) {
                KeyStore trustStore = KeyStore.getInstance("PKCS12");
                trustStore.load(null, null);
                trustStore.setCertificateEntry("ca", loadCertificate(cafile));
                tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
                tmf.init(trustStore);
            }

            SSLContext context = SSLContext.getInstance("TLS");
            context.init(kmf == null ? null : kmf.getKeyManagers(), tmf == null ? null : tmf.getTrustManagers(), null);
            return context;
        } catch (IOException e) {
            throw e;
        } catch (Exception e) {
            throw new IOException("failed to build SSL context", e);
        }
    }

    /** Client-side context: certfile/keyfile present the caller's own identity (mTLS), cafile
     * verifies the peer. check_hostname is never enabled here (matches router_py's
     * ssl_utils.build_client_context), so no endpoint identification algorithm is set below. */
    public static SSLContext buildClientContext(String certfile, String keyfile, String cafile) throws IOException {
        return buildContext(certfile, keyfile, cafile);
    }

    /** Server-side context: certfile/keyfile are required (this actor's identity); cafile, if
     * present, additionally demands and verifies a client certificate (mutual TLS). */
    public static SSLContext buildServerContext(String certfile, String keyfile, String cafile) throws IOException {
        return buildContext(certfile, keyfile, cafile);
    }

    /** Plain, unbound ServerSocket when !sslActive; an unbound SSLServerSocket otherwise - callers
     * keep doing their own setReuseAddress()/bind()/setSoTimeout(), same as before this existed. */
    public static ServerSocket createServerSocket(boolean sslActive, String certfile, String keyfile, String cafile)
            throws IOException {
        if (!sslActive) {
            return new ServerSocket();
        }
        SSLServerSocketFactory factory = buildServerContext(certfile, keyfile, cafile).getServerSocketFactory();
        SSLServerSocket socket = (SSLServerSocket) factory.createServerSocket();
        if (cafile != null) {
            socket.setNeedClientAuth(true);
        }
        return socket;
    }

    /** Plain, unconnected Socket when !sslActive; an unconnected SSLSocket otherwise - callers
     * keep doing their own connect(host, port, timeout). The TLS handshake happens lazily on the
     * connection's first read/write, same as a plain socket only "does" TCP on first use. */
    public static Socket createSocket(boolean sslActive, String certfile, String keyfile, String cafile)
            throws IOException {
        if (!sslActive) {
            return new Socket();
        }
        SSLSocketFactory factory = buildClientContext(certfile, keyfile, cafile).getSocketFactory();
        return factory.createSocket();
    }
}
