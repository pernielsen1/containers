#include <catch2/catch_test_macros.hpp>

#include "shared/stats.h"

// Port of router_py's tests/test_stats.py latency tests / router_java's StatsTest.java latency
// tests. (No general StatsTest.cpp existed before this - only covering the Phase 5 addition.)

using namespace xv6::shared;

TEST_CASE("latency percentiles", "[stats]") {
    Stats s(std::nullopt);
    // 1..100 ms so percentiles are easy to reason about
    for (int v = 1; v <= 100; ++v) {
        s.record_latency("downstream_rtt", static_cast<double>(v));
    }

    auto snap = s.snapshot();
    auto bucket = snap["latency"]["downstream_rtt"];
    REQUIRE(bucket["count"] == 100);
    REQUIRE(bucket["min_ms"] == 1.0);
    REQUIRE(bucket["max_ms"] == 100.0);
    double p50 = bucket["p50_ms"].get<double>();
    double p95 = bucket["p95_ms"].get<double>();
    REQUIRE(49 <= p50);
    REQUIRE(p50 <= 51);
    REQUIRE(94 <= p95);
    REQUIRE(p95 <= 96);
}

TEST_CASE("latency buckets are independent", "[stats]") {
    Stats s(std::nullopt);
    s.record_latency("queue_wait", 1.0);
    s.record_latency("crypto_rtt", 5.0);
    auto snap = s.snapshot();
    auto latency = snap["latency"];
    REQUIRE(latency.size() == 2);
    REQUIRE(latency["queue_wait"]["count"] == 1);
    REQUIRE(latency["crypto_rtt"]["count"] == 1);
}

TEST_CASE("latency bucket bounded by count", "[stats]") {
    Stats s(std::nullopt);
    for (int v = 0; v < 3000; ++v) {
        s.record_latency("total", static_cast<double>(v));
    }
    auto snap = s.snapshot();
    auto bucket = snap["latency"]["total"];
    // only the most recent kLatencyMaxLen (2000) samples are kept
    REQUIRE(bucket["count"] == 2000);
    REQUIRE(bucket["min_ms"] == 1000.0);
    REQUIRE(bucket["max_ms"] == 2999.0);
}
