@echo off
REM One command to answer "did I break anything?" - run before committing.
REM
REM   scripts\verify.bat
REM
REM Runs, in order: ruff lint, then the python test suite. Exits non-zero if
REM any step fails.
setlocal

cd /d "%~dp0\.."

set "PYTHON=%PYTHON%"
if "%PYTHON%"=="" set "PYTHON=venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo error: '%PYTHON%' not found. Set up the environment first:
    echo   python -m venv venv ^&^& venv\Scripts\pip install -r requirements-dev.txt
    exit /b 1
)

set FAILURES=0

echo.
echo == ruff check ==
"%PYTHON%" -m ruff check .
if errorlevel 1 set /a FAILURES+=1

echo.
echo == python tests ^(pytest^) ==
"%PYTHON%" -m pytest tests/ -q
if errorlevel 1 set /a FAILURES+=1

echo.
if "%FAILURES%"=="0" (
    echo All checks passed.
    exit /b 0
)
echo %FAILURES% check^(s^) failed.
exit /b %FAILURES%
