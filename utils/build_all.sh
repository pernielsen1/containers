#!/bin/bash
cd $HOME/containers
ls
build_venv.sh common
build_venv.sh lab
build_venv.sh sockets
build_venv.sh fastapi/crypto_app

