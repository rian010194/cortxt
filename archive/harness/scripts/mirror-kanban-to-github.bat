@echo off
REM Wrapper for mirror-kanban-to-github.py on Windows
REM Uses the Hermes venv Python interpreter

set PYTHON="C:\Users\rikar\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
set SCRIPT="C:\Users\rikar\cortxt\projects\ai-workspace-control-plane\harness\scripts\mirror-kanban-to-github.py"

%PYTHON% %SCRIPT%
