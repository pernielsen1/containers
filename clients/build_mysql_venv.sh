#!/bin/bash
# builds venv for a python client
mkdir python_mysql
python3 -m venv python_mysql
source python_mysql/bin/activate
pip install mysql-connector-python
# now in vscode just select the python3.12 found in python_mysql/bin/....
