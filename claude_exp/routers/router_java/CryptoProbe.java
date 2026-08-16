import com.router.shared.SslUtils;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

public class CryptoProbe {
    public static void main(String[] args) throws Exception {
        String certfile = "/workspace/config/certs/crypto_host_ssl_active_true_cert.pem";
        String keyfile = "/workspace/config/certs/crypto_host_ssl_active_true_key.pem";
        String cafile = "/workspace/config/certs/crypto_host_ssl_active_true_ca.pem";
        var ctx = SslUtils.buildClientContext(certfile, keyfile, cafile);
        HttpClient client = HttpClient.newBuilder().sslContext(ctx).build();
        HttpRequest req = HttpRequest.newBuilder()
            .uri(URI.create("https://localhost:5099/sys/v1/plugins/emv-plugin"))
            .timeout(Duration.ofSeconds(8))
            .header("Content-Type", "application/json")
            .header("Authorization", "Bearer crypto-token-456")
            .POST(HttpRequest.BodyPublishers.ofString("{\"operation\":\"validate_0100\",\"f2\":\"0\",\"f47\":\"\",\"router_stan\":\"probe\"}"))
            .build();
        long t0 = System.currentTimeMillis();
        try {
            HttpResponse<String> resp = client.send(req, HttpResponse.BodyHandlers.ofString());
            System.out.println("OK " + (System.currentTimeMillis()-t0) + "ms status=" + resp.statusCode() + " body=" + resp.body());
        } catch (Exception e) {
            System.out.println("FAILED after " + (System.currentTimeMillis()-t0) + "ms");
            e.printStackTrace();
        }
    }
}
