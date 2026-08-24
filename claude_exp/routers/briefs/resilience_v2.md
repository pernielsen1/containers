# we have performance - resilience is king
# on auto 
we had a bit of clash on auto - so ask me permission on any changes in side this directory then they are autoapproved - i.e. what happens in routers stays in routers :-) 
## experiment python only in host
we have the routers in docker containers fine for performance.
we have selected python first 
for the following - let's do the changes in host python files first - then when we are good with results commit them to the container world..
not nessecary to keep seperate versions locally we will trust in git - i have committed all including results of last 10 m soak runs
## resilience - be rude 
remember the overall pattern - a router may loose an upstream or downstream connection but always needs to be able to recover and be ready for new connections.
we have added SSL - if a upstream or downstream have changed certificates and we are not synched then we cannot recover - we are in a situation needs to be logged as ERROR
## BE BAD AND DESTRUCTIVE  - code monkeys
I want you to build a destructive attack script which we can run against the solution.
a bit like the code monkeys introduced in netflix if I remember correctly - I wan't to see a solution which will get it self back on track (excluding the SSL - certificates which needs intervention)
