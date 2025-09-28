
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.logging.Logger;

public class QueueObject {
    private static final Logger logger = Logger.getLogger(QueueObject.class.getName());

    private String name;
    private Map<String, Object> config;
    private ArrayBlockingQueue<Object> queue;

    public QueueObject(String name, Map<String, Object> config) {
        this.name = name;
        this.config = config;

        int maxSize = 0;
        try {
            Map<String, Object> queueDetails = (Map<String, Object>) config.getOrDefault("queue_details", Map.of());
            Map<String, Object> queueConfig = (Map<String, Object>) queueDetails.getOrDefault(name, Map.of());
            maxSize = (int) queueConfig.getOrDefault("max_size", 0);
        } catch (ClassCastException e) {
            logger.warning("Invalid config structure: " + e.getMessage());
        }

        logger.info("Creating queue " + name + " with max_size " + maxSize);
        queue = new ArrayBlockingQueue<>(maxSize);
    }

    public void put(Object data) throws InterruptedException {
        queue.put(data);
    }

    public Object get(long timeoutSeconds) {
        try {
            return queue.poll(timeoutSeconds, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return null;
        }
    }
}
