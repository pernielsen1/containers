#!/bin/bash
cd crypto_app
source bin/activate
echo starting server
fastapi dev main.py --port 8080
cd ..
