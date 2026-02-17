#!/bin/bash
# Start the admin dashboard — binds to localhost ONLY (ngrok handles public access)
cd "$(dirname "$0")/backend"
exec /opt/homebrew/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
