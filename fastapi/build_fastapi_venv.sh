#!/bin/bash
# builds venv for a python fastapi clears a possible earlier version good if an update has arrived
# https://askubuntu.com/questions/1285650/cannot-install-python-venv-on-ubuntu-20-04-after-upgrading-from-bionic
# PWD=`pwd`
# echo $PWD
# activate () {
# . $PWD/app/bin/activate
# }
mkdir app
rm -rf app/local_packages
rm -rf app/bin
rm -rf app/include
rm -rf app/lib
rm app/lib64
python3 -m venv app
source app/bin/activate

# activate
which pip
pip install fastapi
pip install "fastapi[standard]"
pip install uvicorn
mkdir app/local_packages
cp ../common/dist/* app/local_packages
pip install app/local_packages/pn_utilities-0.1.tar.gz
deactivate