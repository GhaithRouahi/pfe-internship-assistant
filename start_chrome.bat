@echo off
REM Starts YOUR Chrome with a debug port so the bot can click inside it.
REM Chrome (v136+) refuses the debug port on the default profile, so this uses a dedicated profile folder.
REM Log in to LinkedIn / Indeed / WTTJ once in this window; the session is kept for next time.
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir="%~dp0data\chrome_profile" https://www.linkedin.com/login https://secure.indeed.com/auth https://www.welcometothejungle.com/fr/signin
