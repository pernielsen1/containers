#!/bin/bash
# https://pkiage.hashnode.dev/creating-a-local-python-package-in-a-virtual-environment
# file setup.py and __init__.py are there but small
# https://earthly.dev/blog/create-python-package/
TARGET_DIR="common"
mkdir $TARGET_DIR
rm -rf $TARGET_DIR/local_packages
rm -rf $TARGET_DIR/bin
rm -rf $TARGET_DIR/include
rm -rf $TARGET_DIR/lib
rm $TARGET_DIR/lib64
python3 -m venv $TARGET_DIR
source $TARGET_DIR/bin/activate
cd $TARGET_DIR
pip install -r ../common_requirements.txt
# now build the pn_utilities package
python3 setup.py sdist
# Doesn' seem to be necessary to install in of common see test.py in root
deactivate
cd ..
