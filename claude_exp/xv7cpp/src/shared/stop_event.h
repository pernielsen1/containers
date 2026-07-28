#pragma once

#include <chrono>
#include <condition_variable>
#include <mutex>

namespace xv6::shared {

// Write-once stop flag. Backed by a condition_variable (not a bare polled atomic<bool>) so
// wait_for() wakes immediately on set() rather than only at the next poll tick -- matching
// Java's CountDownLatch.await(timeout) semantics.
class StopEvent {
public:
    void set() {
        std::lock_guard<std::mutex> lock(mutex_);
        flag_ = true;
        cv_.notify_all();
    }

    bool is_set() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return flag_;
    }

    // Returns true if the event was set before the timeout elapsed.
    bool wait_for(std::chrono::milliseconds timeout) {
        std::unique_lock<std::mutex> lock(mutex_);
        return cv_.wait_for(lock, timeout, [this] { return flag_; });
    }

    void await() {
        std::unique_lock<std::mutex> lock(mutex_);
        cv_.wait(lock, [this] { return flag_; });
    }

private:
    mutable std::mutex mutex_;
    std::condition_variable cv_;
    bool flag_ = false;
};

}  // namespace xv6::shared
