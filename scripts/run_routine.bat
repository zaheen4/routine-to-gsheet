@echo off
rem Windows counterpart to run_routine.sh: runs the scraper, then the
rem formatter only if the scraper succeeded.
setlocal

rem Get the directory where this script is located and cd to the project root.
cd /d "%~dp0.."

rem Determine the correct Python executable path.
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXEC=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXEC=venv\Scripts\python.exe"
) else (
    echo Virtual environment Python executable not found. Please create one named .venv or venv.
    exit /b 1
)

echo Starting routine scraper (official class routine report)...
"%PYTHON_EXEC%" extract_ucam.py --output output/routine_data.json
if errorlevel 1 (
    echo Scraper failed. Skipping formatter and calendar export.
    exit /b 1
)

echo Scraper finished. Starting gsheet formatter...
"%PYTHON_EXEC%" gsheet_formatter.py --data output/routine_data.json
if errorlevel 1 (
    echo Formatter failed.
    exit /b 1
)

echo Formatter finished. Writing calendar file...
"%PYTHON_EXEC%" ics_exporter.py --data output/routine_data.json --output output/routine.ics
if errorlevel 1 (
    echo Calendar export failed.
    exit /b 1
)

echo Done.
endlocal
