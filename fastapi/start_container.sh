#!/bin/bash
export APP_PORT=8001
echo "port" + $APP_PORT
docker compose up -d
export APP_PORT=8002
docker compose up -d
