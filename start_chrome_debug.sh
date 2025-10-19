#!/bin/bash
echo "Starting Chromium in debug mode on port 9222..."

# Find the correct command for Chromium
if command -v chromium-browser &> /dev/null; then
    BROWSER_CMD="chromium-browser"
elif command -v chromium &> /dev/null; then
    BROWSER_CMD="chromium"
else
    echo "Error: 'chromium-browser' or 'chromium' command not found." >&2
    echo "Please install it using: sudo apt update && sudo apt install chromium -y" >&2
    exit 1
fi

echo "Using command: $BROWSER_CMD"
$BROWSER_CMD --remote-debugging-port=9222 --user-data-dir="$(dirname "$0")/chrome-debug-profile" --no-sandbox
