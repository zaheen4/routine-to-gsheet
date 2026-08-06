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

echo Starting routine scraper...
"%PYTHON_EXEC%" routine_scrapper.py
if errorlevel 1 (
    echo Scraper failed. Skipping formatter.
    exit /b 1
)

echo Scraper finished. Starting gsheet formatter...
"%PYTHON_EXEC%" gsheet_formatter.py
if errorlevel 1 (
    echo Formatter failed.
    exit /b 1
)

echo Done.
endlocal
