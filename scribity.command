#!/bin/bash
echo "============================================"
echo "       SCRIBITY - Starting Up..."
echo "============================================"
echo ""

# Navigate to the script's directory
cd "$(dirname "$0")"

echo "Starting server at http://localhost:8000"
echo "Press Ctrl+C to stop the server."
echo ""

# Open browser after a short delay (background)
(sleep 2 && open "http://localhost:8000") &

# Start the Flask server
python3 scribity_server.py
