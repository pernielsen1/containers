#include <catch2/catch_test_macros.hpp>

#include "router/trace_recorder.h"

// Port of router_py's tests/test_trace.py / router_java's TraceRecorderTest.java.

using namespace router;

TEST_CASE("disarmed by default", "[trace]") {
    TraceRecorder trace;
    REQUIRE_FALSE(trace.start("000001", "100001", "4111111111111111", "0100", {0x01, 0x02}));

    auto snap = trace.snapshot();
    REQUIRE(snap["armed"] == false);
    REQUIRE(snap["remaining"] == 0);
    REQUIRE(snap["entries"].empty());
}

TEST_CASE("arm captures and auto-disarms after count", "[trace]") {
    TraceRecorder trace;
    trace.arm(1);

    bool started = trace.start("000001", "100001", "4111111111111111", "0100", {0xde, 0xad});
    REQUIRE(started);
    REQUIRE(trace.snapshot()["armed"] == false);  // count exhausted

    // a second transaction shouldn't be captured now that the count is used up
    REQUIRE_FALSE(trace.start("000002", "100002", "4111111111111111", "0100", {0xbe, 0xef}));
}

TEST_CASE("hop and finish build full entry", "[trace]") {
    TraceRecorder trace;
    trace.arm(1);
    trace.start("000001", "100001", "4111111111111111", "0100", {0x01, 0x02});

    trace.hop("000001", "crypto_call", nullptr, {{"crypto_ms", 1.5}, {"enriched", true}});
    std::vector<uint8_t> downstream_raw = {0x03, 0x04};
    trace.hop("000001", "downstream_send", &downstream_raw);
    trace.finish("000001");

    auto snap = trace.snapshot();
    REQUIRE_FALSE(snap["entries"].empty());
    auto entry = snap["entries"][0];
    REQUIRE(entry["router_stan"] == "000001");
    REQUIRE(entry["upstream_stan"] == "100001");
    REQUIRE(entry["pan"] == "4111111111111111");

    auto hops = entry["hops"];
    REQUIRE(hops.size() == 3);
    REQUIRE(hops[0]["stage"] == "upstream_recv");
    REQUIRE(hops[1]["stage"] == "crypto_call");
    REQUIRE(hops[2]["stage"] == "downstream_send");
    REQUIRE(hops[0]["wire_hex"] == "0102");
    REQUIRE(hops[2]["wire_hex"] == "0304");
    REQUIRE(hops[1]["crypto_ms"] == 1.5);
    REQUIRE_FALSE(entry.contains("_started_at_ns"));
}

TEST_CASE("hop on untracked stan is a noop", "[trace]") {
    TraceRecorder trace;
    trace.arm(5);
    // never called start() for this stan - simulates a transaction that wasn't selected by arm()
    std::vector<uint8_t> raw = {0x00};
    trace.hop("999999", "downstream_recv", &raw);
    REQUIRE(trace.snapshot()["entries"].empty());
}

TEST_CASE("filter by upstream stan", "[trace]") {
    TraceRecorder trace;
    trace.arm(5, "100002");
    REQUIRE_FALSE(trace.start("000001", "100001", "4111111111111111", "0100", {}));
    REQUIRE(trace.start("000002", "100002", "4111111111111111", "0100", {}));
}

TEST_CASE("filter by pan", "[trace]") {
    TraceRecorder trace;
    trace.arm(5, "", "4222222222222222");
    REQUIRE_FALSE(trace.start("000001", "100001", "4111111111111111", "0100", {}));
    REQUIRE(trace.start("000002", "100002", "4222222222222222", "0100", {}));
}

TEST_CASE("abandon in progress marks incomplete and clears", "[trace]") {
    TraceRecorder trace;
    trace.arm(1);
    trace.start("000001", "100001", "4111111111111111", "0100", {0x01});

    auto abandoned = trace.abandon_in_progress();
    REQUIRE(abandoned.size() == 1);
    REQUIRE(abandoned[0]["incomplete"] == true);

    auto snap = trace.snapshot();
    REQUIRE(snap["entries"].size() == 1);
    REQUIRE(snap["entries"][0]["incomplete"] == true);

    // in-progress table is cleared - a late hop() call for this stan is now a no-op
    trace.hop("000001", "downstream_recv");
    REQUIRE(trace.snapshot()["entries"].size() == 1);
}

TEST_CASE("rearming clears previous filters", "[trace]") {
    TraceRecorder trace;
    trace.arm(1, "100001");
    trace.arm(3);  // re-arm without a filter
    REQUIRE(trace.start("000001", "999999", "4111111111111111", "0100", {}));
}
