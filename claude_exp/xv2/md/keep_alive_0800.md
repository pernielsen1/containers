# 0800 and monitor sockets alive
make a plan for the following - ask questions if unclear
## 0800 into
The 0800 network management iso message is used for ensuring there is traffic on the lines - meaning that "silence" can be observed and alerts raised.
0800 in message type and 100 in field 24 is sent by the originator
0810 in message type is then replied by the other end echoing the field 24
initially the upstream_server will create an 0800 message every ping_0800_seconds - configurable in the json file - initially we set it to 30 seconds.

## sockets alive
if an actor in the chain is stopped - the other actors should understand this and thus also terminate current session.
The router should understand that it is needs to reestablish connection when the other actors wakes up (in this respect the simulators which I will stop and cancel in the monitor web page)
If router is server it will cancel current connection to upstream_host & downstream_host - reestablish downstream_host and when successful start listening for upstream_host.
if router is client it will cancel current connection to upstream host & downstream host - reestablish downstream_host and when successfull try to connect to upstream_host.
the router will wait "reestablish_seconds" before attempting to retry - init to 10 seconcs


