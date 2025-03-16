#!/bin/bash
# builds venv for a python fastapi clears a possible earlier version good if an update has arrived
# https://askubuntu.com/questions/1285650/cannot-install-python-venv-on-ubuntu-20-04-after-upgrading-from-bionic
# PWD=`pwd`
# echo $PWD
# activate () {
# . $PWD/$TARGET_DIR/bin/activate
# }
TARGET_DIR="crypto_app"
mkdir $TARGET_DIR
rm -rf $TARGET_DIR/local_packages
rm -rf $TARGET_DIR/bin
rm -rf $TARGET_DIR/include
rm -rf $TARGET_DIR/lib
rm $TARGET_DIR/lib64
python3 -m venv $TARGET_DIR
source $TARGET_DIR/bin/activate

# activate
which pip
pip install fastapi
pip install "fastapi[standard]"
pip install uvicorn
mkdir $TARGET_DIR/local_packages
cp ../common/dist/* $TARGET_DIR/local_packages
pip install $TARGET_DIR/local_packages/pn_utilities-0.1.tar.gz
deactivate