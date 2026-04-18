virtual environment:
pip install pyiso8583
pip install pandas


objective: build a python application who can test authorization messages in ISO8583 format.

Message_formatting:
The messages should be created / parsed using the already installed pyiso8583 package implementing the class iso8583 and using the format defined in test_spec in file iso_spec.py in this current directory

client and server: the solution should contain a client and a test_server - used when validating.
The client and server communicates over a TCP/IP connection. 
they port they are communicating on is passed as parameter --port and defaults to 1042.
for client a parameter --host defaulting to localhost defining the IP-address or name where the server is located.
The server should only accept one client -  when no client is accepted for 120 seconds the server stops.
the client should wait a maximum of 60 seconds for the server to be active.
Each message is formatted with a length field followed by data. 
the length field is a 32 bit integer (big endian) and contains the length of the data.
data are the encoded iso8583 messages.
The client and server is started as two seperate processes and thus the first parameter to the python program should be client or server to define the role. 
both server and client should have two threads after the connection has been established one for receiving messages and one for sending messages. 
in addition there should be a third thread command.
command is the web server receiving commands it shows a web page on localhost:command_port
command_port is passed as parameter --command_port and defaults to 1043 if role is server and 1044 if role is client.
it is not necessary for the client to wait for having received an answer to message number 1 before sending the next message. 
for each 50 messages - make a little wait for 10 seconds - just to make sure we don't overflood everything.
all wait times - should be configurable in config.json which will have one section for client and another for server.

client:
the client reads test_cases.csv which contains the data for creating a test authorization message.
the column headings are the names defined in the test_spec  like t, 2, 3 etc. 
Note 1: not all have to be filled. 
Note 2: There may be fields in csv not defined in test_spec they should be ignored and example in test_cases.csv is the comment column
for each row an iso message is created (encoded) and sent to the server.
when client receives the response it writes is to a csv file "results.csv".
Note 3: there is no guarantee that responses are received in the order they have been sent in.

server:
the server receives the message and decodes it it. 
If field 2 is starts with 543210 then the field 39 is set to 00 i.e. approved and field 38 to a 6 digit code formatted as a string with zero padding to the left. The code should be incremented for each message approved.
if field 2 does not start with 543210 then the message is declined i.e. field 39 is set to '01'


Further instructions 1:
client should wait until no of replies received equals no of test cases sent or max 20 seconds
server should shutdown after 120 seconds if no inbound messages received
implement a --verbose default = on i.e. a variable verbose has value True if on
if verbose then  display information of messages - hex dump.
hex dump is display length of message received the length field converted to a integer plus a hex notation of the data received

further instructions 2:
build a test driver starting both a server and client running the test cases from test_cases.csv

further instructions 3:
tried to run it got error message 2026-04-18 20:25:19,932 [send] WARNING Encode/send error STAN=000001: can't concat     
  dict to bytes - 
try to run it yourself and correct the error     

further instructions 4:
summarize learnings on iso8583 as skill iso8583 make skill file in current directory

further instructions 5:
make export.sh script making the packages from the venv pandas and pyiso8583 available in a tar file i can import on another machine
make import.sh script which enables med to import the packages in the tar above possible to import on the other machine

result:
  - export.sh — downloads wheels for pandas, pyiso8583, and all dependencies (numpy, python-dateutil, six) into            
  pkg_export/, then packs them into iso8583_packages.tar.gz (~28 MB).                                                      
  - import.sh — extracts the tar and installs everything with pip --no-index (no internet needed). Optionally takes the tar
   path as an argument: ./import.sh /path/to/iso8583_packages.tar.gz.                                                      
                                                                                                                           
  Note: the wheels are built for Python 3.12 on Linux x86_64 — the target machine needs a matching Python version. If the  
  target differs, re-run export.sh there or on a matching machine.         