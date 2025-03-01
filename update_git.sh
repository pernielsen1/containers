#!/bin/bash
# https://www.datacamp.com/tutorial/set-up-and-configure-mysql-in-docker
# Add all files to be tracked
git add .
# commit tracked will open nano for message 
git commit 
# cpnfigure a remote # the URL is without https i.e. userid needs to be provied with token
REMOTE_URL="github.com/$GIT_USER/containers.git"
# push to a remote repository
git push -u https://$GIT_USER:$GIT_ACCESS_TOKEN@$REMOTE_URL main