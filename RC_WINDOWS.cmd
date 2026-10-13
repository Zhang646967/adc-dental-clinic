@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if "%~1"=="" goto usage
if /I "%~1"=="verify" goto verify
docker info >nul 2>nul
if errorlevel 1 (
 echo ERROR: Docker Desktop Linux engine is required.
 exit /b 1
)
set "ENDPOINT="
for /f "delims=" %%H in ('docker context inspect --format "{{.Endpoints.docker.Host}}"') do set "ENDPOINT=%%H"
echo %ENDPOINT%|findstr /b /c:"npipe://" /c:"unix://" >nul
if errorlevel 1 exit /b 2
if defined DOCKER_HOST (
 echo %DOCKER_HOST%|findstr /b /c:"npipe://" /c:"unix://" >nul
 if errorlevel 1 exit /b 2
)
if /I "%~1"=="prepare" goto prepare
if not exist .rc\compose.env (
 echo Run RC_WINDOWS.cmd prepare in a new extraction first.
 exit /b 2
)
docker run --rm --network none -v "%cd%:/workspace" -w /workspace python:3.13-slim python scripts/rc_config.py validate --root /workspace
if errorlevel 1 exit /b 2
set /p PROJECT=<.rc\project.txt
REM Prevent ambient Compose configuration from choosing a different namespace.
set "COMPOSE_PROJECT_NAME="
set "COMPOSE_FILE="
set "RC_PROJECT="
set "RC_APP_SECRET="
set "RC_DB_PASSWORD="
set "RC_WEB_PORT="
set "RC_READ_ONLY="
set "DC=docker compose --env-file .rc\compose.env --project-directory "%cd%" -p %PROJECT% -f compose.rc.yaml"
if /I "%~1"=="status" goto status
if /I "%~1"=="stop" goto stop
if /I "%~1"=="start" goto start
if /I "%~1"=="new-demo" goto newdemo
if /I "%~1"=="import-copy" goto importcopy
goto usage
:newdemo
if not "%~2"=="--synthetic-empty-only" goto usage
call :fresh
if errorlevel 1 exit /b 2
%DC% build
if errorlevel 1 exit /b 1
%DC% up -d db
if errorlevel 1 exit /b 1
%DC% run --rm schema
if errorlevel 1 exit /b 1
%DC% run --rm --no-deps web python manage.py bootstrap_release_demo > .rc\private\demo-credentials.txt
if errorlevel 1 exit /b 1
> .rc\READY echo synthetic-demo
> .rc\SOURCE_MODE echo fresh-demo
echo Demo data prepared. Review private credentials locally, then RC_WINDOWS.cmd start.
exit /b 0
:importcopy
if not "%~2"=="--trusted-synthetic-copy" goto usage
if not exist .rc\private\source.dump (
 echo Missing .rc\private\source.dump. Copy your private synthetic backup; never send it to chat.
 exit /b 2
)
call :fresh
if errorlevel 1 exit /b 2
%DC% build
if errorlevel 1 exit /b 1
%DC% up -d db
if errorlevel 1 exit /b 1
REM run web waits for schema unless --no-deps, so explicitly wait for db here.
%DC% up -d --wait db
if errorlevel 1 exit /b 1
%DC% run --rm --no-deps web python scripts/rc_database_guard.py
if errorlevel 1 exit /b 1
%DC% exec -T db pg_restore --list < .rc\private\source.dump > .rc\private\restore-contents.txt
if errorlevel 1 exit /b 1
%DC% exec -T db pg_restore --no-owner --no-privileges --single-transaction --exit-on-error -U adc_rc_owner -d adc_rc_demo < .rc\private\source.dump
if errorlevel 1 exit /b 1
REM Capture data facts BEFORE applying RC schema; never seed or reset passwords on import.
%DC% exec -T db psql -X -U adc_rc_owner -d adc_rc_demo -At < scripts\rc_legacy_snapshot.sql > .rc\private\before-upgrade.txt
if errorlevel 1 exit /b 1
%DC% run --rm schema
if errorlevel 1 exit /b 1
%DC% exec -T db psql -X -U adc_rc_owner -d adc_rc_demo -At < scripts\rc_legacy_snapshot.sql > .rc\private\after-upgrade.txt
if errorlevel 1 exit /b 1
fc /b .rc\private\before-upgrade.txt .rc\private\after-upgrade.txt > .rc\private\upgrade-compare.txt
if errorlevel 1 (
 echo STOP: legacy-data comparison differs. Preserve files; this does not claim upgrade success.
 exit /b 1
)
> .rc\READY echo imported-copy
> .rc\SOURCE_MODE echo imported-v07-copy
echo Copy restored and legacy summary compared. Review logs, then RC_WINDOWS.cmd start.
exit /b 0
:fresh
if exist .rc\READY exit /b 2
if exist .env (
 echo Refusing old working directory. Keep the running source instance untouched.
 exit /b 2
)
docker volume inspect %PROJECT%_rc_data >nul 2>nul
if not errorlevel 1 (
 echo Refusing existing RC data volume. Preserve it; do not automatically delete or reuse it.
 exit /b 2
)
exit /b 0
:start
if not exist .rc\READY (
 echo First prepare a new demo or imported COPY; start never seeds an existing database.
 exit /b 2
)
REM Always reapply schema/collectstatic before starting web or worker for this frozen RC.
%DC% --profile worker stop gateway web notification-worker
if errorlevel 1 exit /b 1
%DC% run --rm schema
if errorlevel 1 exit /b 1
%DC% --profile worker up -d web gateway notification-worker
if errorlevel 1 exit /b 1
%DC% --profile worker ps
echo Local course gateway: http://127.0.0.1:18000 (or configured RC_WEB_PORT).
echo RC started; status is not a business acceptance certificate.
exit /b 0
:stop
%DC% --profile worker stop gateway web notification-worker db
exit /b %errorlevel%
:status
%DC% --profile worker ps
exit /b %errorlevel%
:prepare
docker run --rm --network none -v "%cd%:/workspace" -w /workspace python:3.13-slim python scripts/rc_config.py prepare --root /workspace
exit /b %errorlevel%
:verify
call VERIFY_ISOLATED_WINDOWS.cmd
exit /b %errorlevel%
:usage
echo RC_WINDOWS.cmd prepare ^| verify ^| new-demo --synthetic-empty-only
echo RC_WINDOWS.cmd import-copy --trusted-synthetic-copy ^| start ^| stop ^| status
echo No command modifies the original v0.7 project. This is NOT public deployment.
exit /b 2
