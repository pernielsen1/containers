#!/bin/bash
# the requests file will have a line like this:
# pn_utilities @ file:///home/per-nielsen/containers/common/dist/pn_utilities-0.1.tar.gz#sha256=11b6ab05ea882587b4f86dfcca921b923ef1f91fbcdc91e9cd58d753c836eed6
# this will not match directory on another compouter .. and we cannot use relative 
# so we install i manually and remove it first
# replace $HOME with ../.. 
cp x.txt y.txt
sed -i "/@ file:/d" y.txt
cat y.txt
cd python_restapi
pip install -r ../y.txt
cd ..