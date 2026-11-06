@echo off
cd /d "%~dp0"
echo Starting System Monitor... (close this window to stop)
set SMTP_USER=solankichintan006@gmail.com
set SMTP_PASS=abcd12345
py run.py
pause