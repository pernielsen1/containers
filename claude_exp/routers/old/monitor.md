# introducing the partner perspective
very verbal input and all changes happens in python first - let's have a discussion

real life we have a partner who has a number of connections like
## partner_X
has two connections existing router_1, router_2 and upstream_1 upstream_2
## partner_Y
has only one connection router_y_3 and upstream_y_3
now this connection should be a bit different - the router_y_3 is the client i.e. will connect to upstream_y_3

# UI changes
first screen should should show 
crypto_host
backend 
a list of partners i.e. in our current setup will show partner_x and partner_y - needs to be dynamic based on config files.
for all summaries - no of transactions i/o within last 30, 60 seconds
from here possible to "dig deeper" and see details for a specific actor.
start/stop all actors for crypto_host, backend or a partner

## details for an actor
function for start/stop
show log descending i.e. newest log first.
show details on no of transactions i/o
upload test files.
start trace mode.. 
refresh.

# this session will be a trial and error sessions to find the right GUI
button needed to start the "supporting actors" crypto_host and down_stream.
the partners need to be a list using minimum screen size - think of a real life scenario with 10 partners - perhaps having around 100 routers below them
error - uploading a test csv from repo did not work

# better
It's better - the list of partners will look Ok with a number of partners.
probably just config error - but we need upstream_2 to start as well
upstream_1 is shown in the top list - it should not be there only the crypto_host & downstream_host should be shown here
a bit surprised that I don't see any log messages when I go into an actor first time. 
In the actor view I need to be able to set the logging level (DEBUG, INFO, etc..)

## minor improvements
our upstream simulators have no logging - not even when going into debug all actors should on INFO level as minimum say - connection established

# the memory
we did a stint yesterday focused on python and did not have the to_do_java_cpp.md at that time - look in your memory if we have things who needs to be implemented in java & cpp as well and updata that in our to_do file



