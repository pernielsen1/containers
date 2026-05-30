# UI optimizse
## there may be multiple routers for a partner
update config files so we implement a partner_id router1 belongs to partner_a and router_2 belongs to partner_b
make a router1.01 which is a copy of router1 but of course is serving a new port.
also implement a test client for router1.01 
## update the ui for routers
router overview should be shown per partner with accumulated statistics 
then it should be possible to drill down to the invidual routers.
this change is only for the router - should not affect the simulators or test runner.
expected outcome I will see two partners in the web overview partner_a (with router_1 andr router_1.01 below) and partner_b with router_2 below

## optimize ui.
the ui now shows partners - good the detailed routers should be within the routers partners display,
there is an error as well the totals in the 30s / total does not show the details in the routers.
for now keep the detailed routers display

## error in totals
the partner totals does not update with the sum of the detailed routers

## optimize layout
in the partner card - keep all information in one row the routers are listed below so can be ignored - the 30/60 s and totals can be kept in one row

## test runner is broken
the test runner does not work anymore - gives failed to fetch

## optimize ui 
in the router cards combine the traffic lights in one row i.e. router traffic ligth upstream and downstream traffic light. 
abbrevia upstream to up and downstream to down

## optimize ui - less is more
combine 30/60 and total in one row
put the logs below the "debug selection box"
make a horizontal scrollbart in case there a more routers in a partner than you can see in one display

## error pressong logs 
pressing logs does not work just displays "loading..." - does not show the log anymore

## error in traffic lights 
so router_1.01 is handling traffic currently have total 13/10 - but there are no lights in the detailed traffic lights

## switched model
switched model - the router_1.01 does not show the detailed traffic lights (up and down) even though traffic is flowing.
haiku didn't find it - evaluate and find a solution

