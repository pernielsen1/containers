#!/bin/bash
# https://www.datacamp.com/tutorial/set-up-and-configure-mysql-in-docker
git init -b main
# Add all files to be tracked
git add .
# commit tracked files with a message
git commit -m "First commit" 
# cpnfigure a remote
# the URL is without https i.e. userid needs to be provied with token
REMOTE_URL="$GIT_USER/github.com/containers.git"
REMOTE_URL="github.com/$GIT_USER/containers.git"

echo $REMOTE_URL
git remote add origin $REMOTE_URL
git remote -v
# push to a remote repository
git push -u https://$GIT_USER:$GIT_ACCESS_TOKEN@$REMOTE_URL main