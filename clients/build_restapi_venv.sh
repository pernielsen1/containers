#!/bin/bash
# builds venv for a python client
TARGET_DIR="python_restapi"
mkdir  $TARGET_DIR
python3 -m venv $TARGET_DIR
source $TARGET_DIR/bin/activate
cd $TARGET_DIR	
# remove the local lines - they are absolut and we will install with relative manually below
sed -i "/@ file:/d" ../python_restapi_requirements.txt
pip install -r ../python_restapi_requirements.txt
# install the local package
pip install ../../common/dist/pn_utilities-0.1.tar.gz
# now in vscode just select the python3.12 found in python_mysql/bin/....
cd ..
