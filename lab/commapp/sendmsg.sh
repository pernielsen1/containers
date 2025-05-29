#!/bin/bash
# example with curl
# sendmsg 8079 listen_client "Here we go"
# curl --data "{\"this\":\"is a test\"}" --header "Content-Type: application/json" http://localhost:8079
python3 sendmsg.py "$@"