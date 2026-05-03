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
