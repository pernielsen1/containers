#!/bin/bash
if [ $# -eq 0 ]
    then
        echo "No arguments supplied exiting"
        exit 1
    else
        TARGET_DIR=$1
        echo "Target dir <" $TARGET_DIR "> supplied and will be created/refreshed in current directory"
fi
mkdir $TARGET_DIR
rm -rf $TARGET_DIR/local_packages
rm -rf $TARGET_DIR/bin
rm -rf $TARGET_DIR/include
rm -rf $TARGET_DIR/lib
rm $TARGET_DIR/lib64
python3 -m venv $TARGET_DIR
source $TARGET_DIR/bin/activate

# remove the local lines - they are absolut and we will install with relative manually below
REQ_FILE=${TARGET_DIR}_requirements.txt
echo "req_file:" $REQ_FILE
sed -i "/@ file:/d" $REQ_FILE
pip install -r $REQ_FILE
mkdir $TARGET_DIR/local_packages
cp $HOME/containers/common/dist/* $TARGET_DIR/local_packages
pip install $TARGET_DIR/local_packages/pn_utilities-0.1.tar.gz

