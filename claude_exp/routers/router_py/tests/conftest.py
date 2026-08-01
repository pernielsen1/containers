import os
import sys

_ROUTER_PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROUTER_PY_ROOT)
# UpstreamHostSim now lives in the shared routers/upstream_host/ component, not router_py/simulators/ -
# see routers/upstream_host/build_router.md.
sys.path.insert(0, os.path.join(os.path.dirname(_ROUTER_PY_ROOT), "upstream_host"))
