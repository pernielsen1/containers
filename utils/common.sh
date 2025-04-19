#!/bin/bash
echo "deactivating venv if active and goto common directory and activate"
if command -v deactivate >/dev/null; then
  echo "deactivating active venv" 
  deactivate
fi
echo "activating"
cd $HOME
echo "should be in $HOME"
cd ~/containers/common
# cd ~/containers
source bin/activate
bash


