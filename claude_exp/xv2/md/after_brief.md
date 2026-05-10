back to planning mode.
I have looked at the code - and believe the following constraint from brief.md has not been achived:
The router does not wait for one crypto_host call to complete before accepting the
next request from upstream_host (non-blocking across connections).
current code receives message on socket and then calls the crypto_host - this call is synchronous and next message will not be received until crypto call has completed.
suggest a solution

round two:
proposed solution "thread_per_request" will add the overhead of creating a thread for each message. The router should be designed for high volumes and thus be speed efficient
propose another solution pattern

round three:
looks good - let no of workers be configurable 

after ims_connect:
running run_text_manually.sh with parameter test_one.csv I get nothing happening and end up with an error. 
all servers are up and running at this point (started manually)
what is wrong 

## minor patch
all actors should have an entry in config.json stating iso8583 spec to use - initial value is test_spec.json


