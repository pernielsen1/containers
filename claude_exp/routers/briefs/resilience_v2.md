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

## let's be more destructive build up a queue.. 
so let try the following pattern - upstream host - keeps on sending messages in - the crypto host is Ok on the request before downstrean host (i.e the 0100) but fails on handling the response the (0110) and thus the upstream host doesn't get the reply and will try again
My espectation is we will stop reading upstream at some point but let's see 
store this scenario as part of the resilience tests 

## having build up the queue - let's look at what happens in real world
most likely it will fail on x (being a very low percentage) and what happens is that the upstream host should time out and say (OK we forget this one)
so let's say 10 % (which is a very high number) actually fails - then we still want's to see that the 100 tps is met... 
what is important here is that they synchrounus call to crypto_host is Ok with the pattern fire and forget in a fee milliseconds.. because no one cares about the result anymore...
on this labtop if reply is delayed by more than 200 ms then if's fire and forget.. real life probably in the 50-75 ms range  (the performance of the application right now on this little labtop actually almost covers real life.. so it's close to being real - well when I close all the memory consuming tasks like my vscode editor - ask me to close it when you are ready)
 
# 0120/0130 advice message and 0400/0410 - reversal
The iso8583 protocol is very resilient by the fact that every actor knowns things can go wrong - and in the end we don't wait for synchronous responses - but rather go on and treat the next authorization and see if that goes better. 
## meaning - timeout 0100 triggers reversal 0400 
When an auth (0100) does not get the (0110) the requestor in this case upstream host on timeout will send a 0400 message - basically the layout of the message is similar to the 0100 message - and the purpose is "I know I asked for an authorization - but please just forget it" i.e. even if the downstream host in this case actually has decided to give a 0110 and reserved the money it now knows - no it wasn't for real.
a reversal is acknoledged by the issuer (downstream_host) with a 0410 meaning - I have understood I can forget your 0100 - and even if I have reserved the amount I will now release it.

## STIP processing 
STand In Processing - so a request (0100) times out - but the card holder is waiting for a decision - often issuers will allow for STIP i.e. smaller amounts will be approved by the upstream host  - in this case it is the responsibility of the upstream host to inform (advice) with a 0120 message to the issuer (downstream_host) that hey I have taken a decision on your behalf - as 0120 message is then acknoledged with a 0130 message from the issuer i.e. I have understood your decision.

## no crypto on 0400/0410 and 0120/0130
we will not need to pass the crypto_host for the 0400/0410 & 0120/0130 
basically the reply (0410) and (0130) is just an echo of inbound message (0400 and 0120) where the message type is changed - this acknoledge is done by issuer (downstream_host) but router should understand this and not try to send the message via the crypto_host (which actually was the original culprit in our faked scenario)
