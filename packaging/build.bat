@echo off
REM FOREST's Proxy Auto-updater — обёртка над build.ps1 (тот же результат).
REM Идемпотентно: можно запускать повторно.
setlocal
set "HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%build.ps1" %*
exit /b %ERRORLEVEL%
