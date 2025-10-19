@echo off
echo Starting Chrome for automation in debug mode on port 9222...

REM Find Chrome executable
set "CHROME_PATH=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not exist "%CHROME_PATH%" (
    echo "ERROR: chrome.exe not found."
    pause
    exit /b
)

REM Use a dedicated user profile directory within the project folder.
set "USER_DATA_DIR=%~dp0chrome-debug-profile"
echo "Using profile directory: %USER_DATA_DIR%"

REM Start Chrome with remote debugging
start "Chrome Debug" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir="%USER_DATA_DIR%" --start-minimized

echo "Chrome started. You can now run your Python script."
echo "Keep this command window open."
echo ------------------------------------------------------------------
pause