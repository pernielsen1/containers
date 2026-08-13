import os
import sys

_ROUTER_PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROUTER_PY_ROOT)
# UpstreamHostSim/DownstreamHostSim now live in the shared routers/upstream_host/ and
# routers/downstream_host/ components, not router_py/simulators/ - see their build_router.md.
# routers/ itself (their common parent) goes on sys.path once, and callers use qualified imports
# (from upstream_host.main import ..., from downstream_host.main import ...) rather than a
# bare-name "from main import ..." trick - both components' entry point is literally named
# main.py, so inserting each one's own directory and doing a bare import would collide on the
# same sys.modules["main"] key the moment both are imported in one process, as this test suite does.
sys.path.insert(0, os.path.dirname(_ROUTER_PY_ROOT))
