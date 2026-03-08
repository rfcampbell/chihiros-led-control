#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
PORT=5050
lsof -ti:$PORT | xargs kill 2>/dev/null
sleep 0.5
open http://localhost:$PORT &
chihiros-web --port $PORT
