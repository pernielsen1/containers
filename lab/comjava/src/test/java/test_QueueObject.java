import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeEach;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class QueueObjectTest {

    private Map<String, Object> validConfig;
    private QueueObject queueObject;

    @BeforeEach
    void setUp() {
        Map<String, Object> queueConfig = new HashMap<>();
        queueConfig.put("max_size", 2);

        Map<String, Object> queueDetails = new HashMap<>();
        queueDetails.put("testQueue", queueConfig);

        validConfig = new HashMap<>();
        validConfig.put("queue_details", queueDetails);

        queueObject = new QueueObject("testQueue", validConfig);
    }

    @Test
    void testConstructorWithValidConfig() {
        assertNotNull(queueObject);
    }

    @Test
    void testConstructorWithMissingQueueDetails() {
        Map<String, Object> config = new HashMap<>();
        QueueObject qo = new QueueObject("missingQueue", config);
        assertNotNull(qo);
    }

    @Test
    void testConstructorWithInvalidConfigStructure() {
        Map<String, Object> config = new HashMap<>();
        config.put("queue_details", "invalid_structure"); // Not a Map
        QueueObject qo = new QueueObject("testQueue", config);
        assertNotNull(qo);
    }

    @Test
    void testPutAndGetSuccess() throws InterruptedException {
        queueObject.put("item1");
        Object result = queueObject.get(1);
        assertEquals("item1", result);
    }

    @Test
    void testGetTimeoutReturnsNull() {
        Object result = queueObject.get(1);
        assertNull(result);
    }

    @Test
    void testPutBlocksWhenFull() throws InterruptedException {
        queueObject.put("item1");
        queueObject.put("item2");

        Thread putThread = new Thread(() -> {
            try {
                queueObject.put("item3"); // Should block until space is available
            } catch (InterruptedException e) {
                fail("Put operation was interrupted");
            }
        });

        putThread.start();
        Thread.sleep(500); // Give time for thread to block
        assertTrue(putThread.isAlive());

        queueObject.get(1); // Free up space
        putThread.join(1000); // Should complete now
        assertFalse(putThread.isAlive());
    }
}
