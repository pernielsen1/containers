# move router alternatives into one structure
make a plan and let's discuss before implementing.. 
Three alternative implementations exists of the router, simulators and monitor
python in ../router_py
java in ../router_java 
c++ in ../router_cpp 

each contain a md file describing the complete spec - unfortunately not with the same name - but you know them 

# next goal 
I want to be able to compare the alternatives when set under the same testing pattern - in particular we will be doing performance testing 
expected outcome is obviously that c++ will win over java who will win over python - but what's the treshold.
the solutions hava a complexity which are inverse to the expected performance testing.

# cleaning up
## in sub directory
i would like to see the three alternatives as subdirectories of this directory.
please move them and update git ignore etc and all relevant 
## python router & simulator in container
the router_java and router_cpp are containorized - to make a correct comparison the python (../router_py) should also be in a container - make a container for this as well including the stop.sh and start.sh and mapping to host directories in same pattern as router_java & router_cpp

## learn from pitfalls
when doing the different implementation (java was a successor to python and c++ a sucessor to jav - new pitfalls were discoverd - ensure relevant pitfalls are corrected i.e. let java learn from c++ and python from java.


## testing 
after all have been moved - test that applications still are working
I will do a manual test as well.

## the next goal comparing performance
make a plan for creating a way of stress testing all three implementation - remember they are mutually exclusive so each of them will get their minutes for fame - results recorded before closing down and continuing with next implementation.
the performance results should be summarized in a csv which I can review afterwards.

Done: each implementation's `upstream_host` now takes optional `rate`/`duration` params on `/start`
(cycling the CSV to sustain load) and exposes `/stress_stats` (sent/received/errors/achieved TPS/
latency percentiles). Each implementation has its own `stress_run.sh <tps> <duration> <csv>`, and
`routers/stress_test.sh` sweeps a TPS list across all three in turn, appending one row per
(implementation, tps) run to `routers/stress_results.csv`:
`timestamp;implementation;target_tps;duration_s;sent;received;errors;achieved_tps;p50_ms;p95_ms;p99_ms;max_ms`.
Run `./stress_test.sh` (defaults: tps 50/100/200/400, 30s each) or `./stress_test.sh --tps 50,100 --duration 10` for a quick smoke sweep.

# minor updates
for my conviniency make a start_docker.sh in the root here
# minor updates v2 
for my convinence make a monitor.sh in the root here

# some input 
a thought from my side - pls evaluate 
we receive 0100 from upstream  into router - calls crypto host and sends to downstream 
then we get 0110 back from downstream to router calls crypto host and sends to upstream
now upstream is flooding into the router with 0100 while workers try to catch up. 
the 0110 needs to get into that pool of workers but will perhaps not get the right place since the floowing continues all in all building up a backlog of work. 

# stress test part 2 
we have seen 100 tps as working - now will it also work if we run it for a long time let's say 5 minutes ? 
the run should be with the real crypto_host since that seemed to cope well with this load.
I'm interested in understanding if we at some point get into garbage collection slow down in python and java.
what is interesting to know is what the slowest turn around time (i.e. time between send 0100 and receive 0110 at upstream)
try to record the 10 slowest results and write them to a slow_responds.csv - record time from start of simulation plus the actual time measured for turn around.
start in python 
