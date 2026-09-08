@echo off
rem Double-click to launch the Forum Post Generator (no console window).
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "%~dp0forum_post_generator.py"
