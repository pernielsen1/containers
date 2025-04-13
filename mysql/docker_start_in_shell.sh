#!/bin/bash
echo "passed:"  $1
sudo docker run -it --entrypoint /bin/bash  $1
