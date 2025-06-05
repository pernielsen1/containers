The CO-pilot communication application.
Can you help me write a communication application with the following characteristics in python
all configuration information is read from a json file passed to the program as argv[1].  if no arguments is passed use filename config.json as default.

1. Assumptions:
    1. All socket communication follows a protocol where first a length field is received. 
    2. A config parameter tells which type_of_length field one of the following 2
    3. 1: ascii_4 meaning 4 bytes in ascii telling the length of the actual data to follow.
    4. 2: binary_4 meaning 4 bytes binary in big endian formats has length of the actual data to follow
    5. Socket communication must be non blocking i.e. use the set time out to 0.5 seconds for the socket. 
    6. For logging use standard python logging

2. QueueObject class.
    1. There exists a QueueObject class defining a queue object similar to the python queue class.
    2. The class constructor is initiated with a name plus a dictionary.holding configuration information.
    3. The class implements:
    4. put  a function for sending data taking as input a byte array
    5. get a function receiving data taking as input a timeout parameter in milliseconds - the routing returns a byte array if data was received or None if no data received

3. Messge class
    1. Holds dictionary 
    2. msg = { 
    3.    "data_base64": string, 
    4.    "time_created_ns": int
    5. }
    6. Constructor takes "data" as variable a byte array as argument and creates data_base64 as the base64 encoding of the byte array the time_created_ns is the timestamp for the transaction in nano seconds ie when Message object is created
    7. The class exposes 
    8. get_data returns data_base64 as byte array after base64 decoding-
    9. get_json returns the msg dictionary as as json object
    10. get_create_ns returns the int time_create_ns

4. MessageString class
    1. An extension of message class
    2. Constructor takes string as input. 
    3. The string  is encoded to bytes utf-8 and then stored in the message class as data_base64 base64 encoded.
    4. Exposes get_string returning the data_base64 after converting to byte array and then to utf-8 string

5. Filter class
    1. A filter is constructed with a name and a  run_function which is a python function.
    2. The filter exposes a function "run" taking as input message a Message object and returning an updated Message object.
    3. Exposes a function get_name returning the name of the filter passed in the constructor.


6. CommunicationApplication class
    1. The place where it all starts.
    2. the Constructor of the class is called with a dictionary - the result of reading the config file above. This dictionary is stored in self.config.
    
    3. all functionality assembled in a class CommunicationApplication
    
    4. The class contains a dictionary "filters" containing name as key and an object of the type Filter. 
    5. The class exposes an add_filter function taking a Filter object as input and stores it to the filters dictionary with the Filter.get_name() as key.
    6. The class exposes an get_filter function taking name as input looks up if name exists in filters and if so returns the Filter Object - if not found returns None
    
    7. The class contains a dictionary "queues" containing name as key and an object of the type QueueObject. 
    8. The class exposes method add_queue taking name as input and looks up in "queues" if it exist then returns the QueueObject from the dictionary. If not found then a new QueueObject with the given name is created, stored in "queues" and returned to the caller.

7. CommunicationThread: 

    1. The communication is done with a number of threads all sharing the following setup
    2. A new CommunicationThread is defined as an extension of python thread.
    3. All threads will be extensions of CommunicationThread 
    4. All threads are in held in a list named "threads"in the CommunicationApplication class.
    5. A thread should be added to this list before it is started.
    
    6. Constructor of CommunicationThread takes name, queue_name, exit_if_inactive and filter_name as input -  filter_name has a default value of None.
    7. The object has the following attributes.
        a. heartbeat initiated to current time
        b. active initiated to True
        c. queue initiated by calling the CommunicationApplication.add_queue(self.queue_name)
        d. filter initiated by calling the CommunicationApplication.get_filter(filter_name). 
    8. A thread will typically have a "While true" loop and in the beginning of this loop the thread should update the heartbeat field with the current time. 
    9. If filter <> None the filter.run method should be called with message as parameter just before sending data 
    10. the "BigMama" Thread can set this Boolean to False if it wants the thread to stop. 
    11. Some threads will be waiting for commands from a queue. A command is just a text string received from a QueueObject.
8. SocketReceiverThread
    1. An extension of the CommunicationThread receiving data on a socket creating a message object and passing it on to a QueueObject.
    2. Constructor takes arguments, with socket, length_field_type, queue_name, exit_if_inactive and filter_name 
    3. Enters a while active loop receiving data from the socket
        a. Update heartbeat.
        b. Receives 4 bytes and based on length_field_type calculates the length in bytes of the data to follow.
        c. If length field is received then 
            i. receives length data bytes to variable data a byte array 
            ii. Constructs a  Message from the  data variable and sends it to the queue.
        d.  
9. SocketSenderThread
    1. An extension of the CommunicationThread receiving data from queue and sending data on socket.
    2. Constructor takes arguments, with socket, length_field_type, queue_name, exit_if_inactive and filter_name 
    3. Enters a while active loop receiving data from the queue
        a. Update heartbeat.
        b. If data is received from queue 
            i. Creates a length field according to length field_type and sends on the socket.
            ii. Gets the data as byte array from message and sends this byte array on the socket
        c.  
    4. 
10. big_mama thread 
    1. Initiated by CommunicationApplication with queue_name="big_mama", exit_if_inactive=True and filter_name=None
    2. The thread is monitoring that all other threads are alive and if a thread with exit_if_inactive is not reporting in time then stops all threads and exits the program
    3. All threads must be non blocking an report a heartbeat at least once every 0.5 seconds.
    4. if a thread has not reported in 30 seconds it is considered inactive and will be stopped.
    5. When a thread is having problems an alert should be sent to the log.
    6. When program exiting an alert should be sent to the log.
    7. big_mama starts the following threads which will be described further down
        a. backend_host thread
        b. listen_client 
        c. command_thread
    8. after having started the threads big mama enters a "while active" loop where it receives commands from the internal big_mama queue it will time out on receive every 0.2 seconds. 
    9. when the command stop is received then big_mama will set the active attribute in all threads to False
    10. after having set all threads to False big_mama will loop through threads every 0,5 second for a maximum of 10 seconds until they are no longer active. 
    11. After this big_mama exits the program. 

11. Backend_host thread
12. Initiated with queue_name="backend_host", exit_if_inactive=True and filter_name=None
13. Creates a socket connects to backend server localhost on port 4243 and starts
    1. host_receiver - a SocketReceiverThread initiated with socket, length_field_type=binary_4, queue_name=host_receiver, exit_if_inactive=True and filter_name=host_receiver
    2. host sender -a SocketSenderThread initiated with socket, length_field_type=binary_4, queue_name=host_sender, exit_if_inactive=True and filter_name=host_sender
14. enters into a loop
    1.  waiting for commands in queue backend_host
    2. If command received and = "stop" is received then the thread ends. 

15. Listen_client thread
    1. Initiated with queue_name="listen_client", exit_if_inactive=True and filter_name=None
    2. Starts with looping while waiting for client to connect:
        a. Listens on port 4242 for clients to connect to a socket  
        b. Here the socket will time out if no client and the heartbeat can be updated
        c. When client connects it is accepted and the following threads started 
            i. host_receiver - a SocketReceiverThread initiated with socket, length_field_type=ascii_4, queue_name=from_client, exit_if_inactive=True and filter_name=host_receiver
            ii. host sender -a SocketSenderThread initiated with socket, length_field_type=ascii_4, queue_name=to_client, exit_if_inactive=True and filter_name=host_sender
            iii. a configurable (NUM_WORKERS) number of worker threads named worker_x where x is from 1 to NUM_WORKERS s for initial application set NUM_WORKERS=3
        d. When thread have been started the loop ends
    3. Enters into a new loop waiting for commands in queue listen_client. If the command="stop" is received then the thread ends. 
    
16. worker threads
    1. Initiated with queue_name = "from_client", exit_if_inactive=False and filter_name="from_client"
    2. The worker threads reads messages from queue and applies the filter and then sends the data to queue "host_sender"

17. command_thread
    1. Initiated with queue_name=command, exit_if_inactive=True and filter_name=None
    2. Command_thread is a thread exposing a RESTAPI on port 8079.  It will listen for a client - accept the client and process the request.
    3. The allowed request is /command/stop{queue}
    4. when received the api will create a MessageString and send to the QueueObject named in the parameter  {queue}. 
    5. This command can be used for stopping a routine from the outside.
