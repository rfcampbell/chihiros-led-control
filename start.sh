#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
open http://localhost:5000 &
chihiros-web
