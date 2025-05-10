#!/bin/bash
cd $HOME/containers
cd redis
sudo ./start_container.sh
cd ..
cd mysql
sudo ./start_container.sh

