#!/bin/bash
cd app
source bin/activate
echo starting server
fastapi dev main.py
