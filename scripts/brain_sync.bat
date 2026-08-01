@echo off
REM chcp/PYTHONIOENCODING: sin esto el log sale con mojibake (cmd usa cp850)
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d C:\Users\Administrator\Projects\agency-agents-render\scripts
python brain_sync.py >> brain_sync.log 2>&1
