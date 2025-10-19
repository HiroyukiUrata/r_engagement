#!/bin/bash
echo "Starting Chromium in debug mode on port 9222..."

# Activate virtual environment if it exists to find the playwright command
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Find the executable path of the browser installed by Playwright.
# This command runs a short Python script to get the correct path using the public Playwright API.
BROWSER_EXECUTABLE_PATH=$(python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); print(p.chromium.executable_path); p.stop();")



if [ -z "$BROWSER_EXECUTABLE_PATH" ]; then
    echo "Error: Could not find the browser installed by Playwright." >&2
    echo "Please run 'playwright install' first." >&2
    exit 1
fi

echo "Using Playwright's Chromium: $BROWSER_EXECUTABLE_PATH"

"$BROWSER_EXECUTABLE_PATH" --remote-debugging-port=9222 --user-data-dir="$(dirname "$0")/chrome-debug-profile" --no-sandbox --start-minimized
