"""Per-language backends for the shared monitor. Each module (router_py.py/router_java.py/
router_cpp.py) implements the same contract - see monitor_host/main.py's top-of-file docstring
for the full interface. main.py picks one at startup via --target/MONITOR_TARGET and treats it
as a plain namespace (no ABC/Protocol - three modules is not enough call sites to be worth the
ceremony, and a missing attribute fails loudly and immediately at import/dispatch time anyway)."""
