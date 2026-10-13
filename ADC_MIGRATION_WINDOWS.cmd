@echo off
setlocal
REM Host Python required for migration orchestration. No Django/psycopg required.
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>nul
if errorlevel 1 (
 echo Migration tools require a working Python 3.11+ on PATH.
 echo VERIFY_ISOLATED_WINDOWS.cmd still requires Docker only.
 echo Do not use a broken launcher or copy a Windows virtualenv to the Mac.
 exit /b 2
)
python "%~dp0scripts\migration_tool.py" %*
exit /b %errorlevel%
