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

# Use Scribity's isolated runtime when available so the native file picker and
# Python dependencies always come from the same interpreter.
if [ -x ".venv/bin/python" ]; then
    exec .venv/bin/python start_scribity.py
fi

python3 start_scribity.py
