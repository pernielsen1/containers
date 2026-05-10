    https://www.ibm.com/docs/en/ims/15.4.0?topic=isiccm-format-fixed-portion-irm-in-messages-sent-ims-connect

start by making a plan for the implementation of IMS connect protocol described below. ask questions if errors / inconsequential part of the description. 
# change to IMS connect protocol for downstream_host
a complication utilitizing two sockets - to_downstream_socket and from_downstream_socket
the router first connects to downstream_host on port "to_downstream_port" (configurable)
then router connects to down_stream_host on port "from_downstream_port" and sends one message which is a resume TPIPE i.e. the IRM_F0 is x'80' (see below). 
The data part is 0 i.e. no transcode nor data included in the message - IRM_CLIENT_ID is the last part of the message.
from there on the router then sends data to downstream_host on the "to_downsteream_socket" and receives data on the "from_downstream_socket".

## ims connect protocol
all messages sent to down_stream host will contain an IMS-connect header.
the total layout of the frame will be 
### llll 
4 bytes the Length_field as we know it in BIG_ENDIAN   note length of message will be the original data plus length of IMS-connect header.
### IRM_LEN
two bytes big endian set to integer value 28
### IRM_ARCH
1 byte set to x'04'
### IRM_F0
this is set to x'80' if socket is to be used for a "resume tpipe" (more on this later)
otherwise to x'00'

### IRM_ID
8 bytes - let value be configurable in the json - for example use IRM_ID01 - the value should be translated from ASCII (in the json) to EBCDIC

### IRM_NAK_RSNCDE
2 bytes value x'0000'
### IRM_RES
2 bytes value x'0000'
### IRM_F5
1 byte set to x'00'
### IRM_TIMER
1 byte set to x'15'
### IRM_SOCT 
1 byte set to x'10'
### IRM_ES
1 byte set to x'01'
### IRM_CLIENTID
8 bytes let it be configurable default 'CLIENT01' translate to EBCDIC.
### TRANS_CODE
The transcode is constructed from the message type by prepending TRAN i.e. 0100 message becomes TRAN0100 translated to EBCDIC obs field only included inf len(data) > 0
### data 
after ther transcode comes the actual data to be sent to the downstream_host

### return messsages:  
return messages from downstream_host to router are just encoded with the llll followed by the actual data.
messages from 


# IMS_CONNECT part two
## The pipe cleaner
use skill router.md and make a plan for the following
when router starts up and connects to downstream host it will start with a resume TPIPE on from_downstream_socket. 
then to make sure nothing is waiting it should send a "pipe-cleaner" message - this is a message which it will send on to_downstream_socket where transcode should be PING0001 (in EBCDIC) and the data should be the message "1234 clean the pipes" in EBCDIC.
when downstream host receives the PING0001 transaction code it should just return the message not in an iso message but just "PING" in EBCDIC followed by the "PIPES cleaned" in EBCDIC. 
the router should understand that if first 4 bytes received from downstream_host then it is not an iso8583 message - and it should just display the data in hex and not send it further on to upstream_host.


