#!/bin/bash
# https://pkiage.hashnode.dev/creating-a-local-python-package-in-a-virtual-environment
# file setup.py and __init__.py are there but small
# https://earthly.dev/blog/create-python-package/
TARGET_COMMON="common"
mkdir $TARGET_COMMON
python3 -m venv $TARGET_COMMON
source $TARGET_COMMON/bin/activate
cd $TARGET_COMMON
pip freeze > requirements.txt
pip install -r requirements.txt
pip install setuptools
# now build the pn_utilities package
python3 setup.py sdist
pip install -e .    
deactivate
cd ..
