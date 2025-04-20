#!/bin/bash
cd server
source bin/activate
echo starting TcpServer server
python3 tcp_server.py 
cd ..
