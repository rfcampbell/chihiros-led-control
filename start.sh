#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
lsof -ti:5000 | xargs kill 2>/dev/null
sleep 0.5
open http://localhost:5000 &
chihiros-web
