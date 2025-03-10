#!/bin/bash
# builds venv for a python client
TARGET_DIR="python_restapi"
mkdir  $TARGET_DIR
python3 -m venv $TARGET_DIR
source $TARGET_DIR/bin/activate
cd $TARGET_DIR	
pip install requests
pip install ../../common/dist/pn_utilities-0.1.tar.gz
# pip install ../../pn_utilities
# now in vscode just select the python3.12 found in python_mysql/bin/....
cd ..
