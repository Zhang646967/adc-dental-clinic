@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
echo ADC isolated verification. Your running v0.7 will not be upgraded.
docker info >nul 2>nul
if errorlevel 1 (
  echo ERROR: start Docker Desktop with the Linux engine first.
  exit /b 1
)
for /f "delims=" %%H in ('docker context inspect --format "{{.Endpoints.docker.Host}}"') do set "ENDPOINT=%%H"
echo !ENDPOINT!| findstr /b /c:"npipe://" /c:"unix://" >nul
if errorlevel 1 (
  echo ERROR: select a local Docker Desktop context, not a remote host.
  exit /b 1
)
if defined DOCKER_HOST (
  echo !DOCKER_HOST!| findstr /b /c:"npipe://" /c:"unix://" >nul
  if errorlevel 1 exit /b 1
)
set "PROJECT=adc_verify_%RANDOM%_%RANDOM%_%RANDOM%"
set "EMPTY_ENV=%TEMP%\%PROJECT%.env"
>"%EMPTY_ENV%" echo # Empty verification environment - never load the application .env
if not exist evidence\verification mkdir evidence\verification
set "CONFIG=isolation_%PROJECT%.json"
set "DC=docker compose --env-file "%EMPTY_ENV%" --project-directory "%cd%" -p %PROJECT% -f compose.verify.yaml"
set "RESULT=1"
%DC% config --format json > "evidence\verification\%CONFIG%"
if errorlevel 1 goto finish
%DC% build verify
if errorlevel 1 goto finish
%DC% run --rm --no-deps verify python scripts/verify_isolated.py --validate-config "/evidence/%CONFIG%" --source-root "%cd%"
if errorlevel 1 goto finish
%DC% up --abort-on-container-exit --exit-code-from verify
set "RESULT=!errorlevel!"
:finish
%DC% down --remove-orphans
set "CLEANUP=!errorlevel!"
if exist "%EMPTY_ENV%" del "%EMPTY_ENV%"
echo Isolated project: %PROJECT%
echo Verification return code: %RESULT%
echo Cleanup return code: %CLEANUP%
echo Evidence: %cd%\evidence\verification
echo No existing ADC volume, application .env or password was changed.
if not "%CLEANUP%"=="0" exit /b 1
exit /b %RESULT%
