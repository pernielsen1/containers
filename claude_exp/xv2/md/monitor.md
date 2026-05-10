# monitor 
## Intro
making it a bit more complicated use skill router and come up with a plan for the following
do ask questions if irregularities in the input.
## making it multi
the router is a 24/7 process and there will be several instances of it - each servicing seperate upstream_hosts each on a different port.
downstream_host will be capable of servicing multiple instances of routers on the same ports i.e. it can accept a client and start listening for a new. Since a router will open two sockets they need to be paired this is done using the IRM_CLIENTID which should be the same both for the "resume t-pipe" used in "from_downstream_socket" and when sending input to the "to_downstream_socket". 
the downstream_host should accept both "from_downstream" and "to_downstream" requests on the same port and use the first message received to determine what it is -  a resume TPIPE means "from_downstream" i.e. where downstream_host send it resplies a "Non resume TPIPE" means the input socket where downstream_host receives the requests.

There is still only one instance of crypto_host in simulation - in production it will be behind a load balancer with multiple instances.

so in initial setup let us have 
### two upstream_hosts 
named upstream_1 and upstream_2 (names should be in the config.jsons)
### two routers 
named router_1 servicing upstream_1 and router_2 servicing upstream_2 on two different ports.
### one crypto_host
like we have it today
### one downstream_host
servicing both router_1 and router_2

## the monitor and controller.
with many processes both simulators and the routers we need the ui to control them. 
it should be split in two sections -  simulators and routers.
The process for "running tests" only available in the simulator section.
