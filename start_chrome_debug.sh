#!/bin/bash
echo "Starting Chromium in debug mode on port 9222..."
chromium-browser --remote-debugging-port=9222 --user-data-dir="$(dirname "$0")/chrome-debug-profile" --no-sandbox