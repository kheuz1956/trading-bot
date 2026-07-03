@echo off
REM Lanceur unique du signal runner US100.
REM Tue toute instance existante puis demarre une seule instance (stdout valide => pas de gel).
cd /d "%~dp0"
echo [start_bot] Arret des instances existantes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*signal_runner.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo [start_bot] Demarrage signal_runner.py...
"C:\Users\CHEIKH MBACKE DIENG\AppData\Local\Programs\Python\Python312\python.exe" -u signal_runner.py
