# introduction
commapp can drive several types of communication applications built up around sockets, queues, filters, workers and a simple http server.
The main example consists of\
**client** - an application which will send a iso8583 0100 message to\
**middle** - and application receiving on socket (from client) the iso8583 request, parses it, jump out to crypto server to complete an arqc and finally send the request to backend.\
**backend** -  a simple backend simulator who will simply see if we should approve and creates a 0110 answer which goes back to\
**middle** - who will parse the request, jump out to crypto server to calculate an arpc and send the result to\ 
**client** - who will log the result.\

socket connections between client, middle and backend are kept open.
a TCP message starts with a length field i.e. 4 bytes of ascii or 4 binary bytes.
all configuration are kept in the config directory and will have same name as applications above i.e. middle.json is the config file for the middle processes.

supporting cast
**testmsg** who can initiate a test by connecting to the http server for **client** 
**crypto_server** receives json request and performs arqc or arpc calculation 

## client
client starts by connecting to **middle** on a socket 

## middle
## backend
## crypto_server
## testmsg

