package com.xv6.shared;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Write-once stop flag, matching the {@code threading.Event} usage pattern in xv5 (set once from
 * a command route, waited on with a timeout by the actor's main loop). Backed by a
 * single-count {@link CountDownLatch} since the flag is never unset.
 */
public final class StopEvent {

    private final CountDownLatch latch = new CountDownLatch(1);

    public void set() {
        latch.countDown();
    }

    public boolean isSet() {
        return latch.getCount() == 0;
    }

    /** Returns true if the event became set before the timeout elapsed. */
    public boolean waitFor(long timeout, TimeUnit unit) throws InterruptedException {
        return latch.await(timeout, unit);
    }

    public void await() throws InterruptedException {
        latch.await();
    }
}
