# the big question
we have stable implementation who can all safely run 80 tps which is good enough - after all we are on a labtop 
so what should I choose to continue with

It seams the solutions (perhaps not surprising) has this pattern

router_py:  Simple in terms of understanding the code - slowest of the pack delivering 80
router_java:  More complex than python and delivers the 100 with max who are approacing 0,3 seconds
router_cpp: Most complex and by far the fastest.

Update this document with some pro's and con's for the three solutions starting next line

## router_py (Python)

**Pros**
- By far the easiest to read, modify, and extend — dataclasses, no build step, no compiler between
  you and a running process. Every feature this project needed landed here first and cleanest.
- Fastest dev loop of the three: edit, restart, done. No Docker rebuild, no `mvn package`. Directly
  saved real time this session (contrast the multi-minute router_cpp Docker rebuilds every time a
  shared header changed).
- `pyiso8583` is a real, maintained ISO 8583 library — the wire format is data-driven from a spec
  file, not hand-rolled, so a new field/encoding is a config change, not new parsing code.
- Widest realistic hiring/onboarding pool if this ever needs a second pair of hands.

**Cons**
- Slowest of the three by a wide margin, and the only one that didn't clear 100 tps cleanly in
  testing — it's already running close to its comfortable ceiling on this laptop.
- Bug class we actually hit: wrong/missing constructor kwargs only fail at runtime (`TypeError:
  unexpected keyword argument`), not at edit time — Java's typed records made the same mistake
  structurally impossible.
- Least headroom for growth — more partners, more TPS, or a heavier per-message workload (e.g.
  real crypto in the loop) will bite here first.

## router_java (Java)

**Pros**
- Real headroom over Python (100 tps clean, p50 ~53ms in the last soak run) while staying memory-
  safe — no manual memory management, no segfault class of bug at all.
- Statically typed end to end; the exclusion-set bug class above is compiled away entirely via
  Jackson's typed records + `ignoreUnknown`.
- `j8583` is a mature, standards-based codec — same "spec file, not hand-rolled parser" advantage
  as Python's `pyiso8583`, though with its own real gotchas found this session (binary bitmap
  default, and EBCDIC needing `setForceStringEncoding` alongside `setCharacterEncoding`).
- Enterprise/mainframe-adjacent tooling maturity is a genuine fit for an IMS-Connect-style
  downstream — this is well-trodden ground for the JVM ecosystem.

**Cons**
- Noticeably more code/ceremony than Python for the same behavior (records, explicit typing,
  more boilerplate around config).
- Needs a build step (Maven) — slower than Python's edit-restart loop, though far faster than
  router_cpp's Docker rebuild cycle.
- Latency tail is the one place it doesn't look Python-like *or* C++-like: max latency (378ms in
  the last run) was ~20x router_cpp's, even though p50/p95/p99 were all much closer to C++ than to
  Python — consistent with occasional GC/JIT-warmup pauses, not a queueing problem.
- Heavier production footprint — needs a JVM at runtime, unlike C++'s single static-ish binary.

## router_cpp (C++)

**Pros**
- Fastest by a wide margin on every metric, not just the average — p50 ~2.4ms, max ~19ms in the
  last soak run, roughly an order of magnitude better than either alternative across the board.
- Most predictable tail latency of the three (no GC, no VM warmup) — the metric that matters most
  if this ever needs to scale to more partners/TPS on the same hardware rather than bigger hardware.
- Smallest, most self-contained deployment artifact — a native binary, no runtime dependency.

**Cons**
- By far the most complex and riskiest to maintain safely. No mature ISO 8583 library exists for
  it — the codec is hand-rolled, and it has had real, otherwise-invisible wire-format bugs because
  of that (an MTI-encoding mismatch found migrating to the shared load generator, and this
  session's EBCDIC length-prefix handling, both things `pyiso8583`/`j8583` would have gotten right
  by construction).
- Hit an actual segfault during development (a self-referential lifetime bug between `Dispatcher`
  and `DownstreamConnection` after a move) — a whole bug class that's categorically impossible in
  Python or Java. That risk doesn't go away; it just hasn't bitten again yet.
- Slowest, most fragile iteration loop of the three: multi-minute Docker rebuilds on every source
  change (repeatedly the actual bottleneck in this session's work), and the build itself is
  memory-constrained on this laptop (`-j1`/`-j2` OOM risk, documented in `build_router.md`).
- Smallest realistic pool of people who can safely extend it without reintroducing a memory-safety
  bug.

## One thing worth naming directly

You already said 80 tps is good enough on this laptop — so the honest deciding factor here isn't
"which one is fastest," all three clear that bar. It's "which one do you want to be debugging
and extending a year from now." router_py wins on that question outright if TPS truly stays
laptop-scale forever. router_java is the middle ground if you expect real (not laptop-scale)
production load eventually but still want to sleep at night about memory bugs. router_cpp only
earns its complexity if squeezing maximum throughput per CPU core is actually the point of the
exercise, rather than a side effect of comparing three languages.
