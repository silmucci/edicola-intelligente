@echo off
cd /d "%~dp0"
rem Scelta locale limitata a questo processo; nessun file di configurazione cambia.
set "EDICOLA_CLOUD_DEMO=0"
"%~dp0.venv\Scripts\python.exe" -X utf8 -m edicola.archive_manager
pause
