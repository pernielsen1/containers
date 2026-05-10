# router as client to upstream_host
make a plan for making router able to be a client as well.
in current setup router is always server for upstream_host.
router needs to be able to work in both modes for upstream_host i.e. can also be a client = connecting to upstream_host.
if upstream_host is not available (not listening) it should try to connect with an interval of "retry_seconds".
in our current setup let router_2 be client i.e. upstream_host_2 will be server.

