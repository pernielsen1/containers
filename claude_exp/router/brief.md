create a compose.yaml creating a development container for java
the containers app directory should be mapped to the hosts current directory
the container should allow other clients to access the port defined in host environment variable 
$BACKEND_PORT reading this variable as part of "docker compose up".
the variable $BACKEND_PORT should be available in the container

In the current directory create the backend application java project.
backend is a java application inplementing a TCP/IP server listening on port 
defined in environment variable $BACKEND_PORT. 
the server should only accept one client. 
the client will send messages start with a length_field (4 bytes, big endian)
followed by the "length_field" number of bytes.
the server should have    


