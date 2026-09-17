@echo off
title Xiyu - DIAGNOSE login
echo.
echo ======================================================
echo   LOGIN DIAGNOSIS
echo.
echo   Asks SSH itself why the login is refused.
echo   Does not need the key to work.
echo   Read-only: nothing on the server is changed.
echo.
echo   This window STAYS OPEN even if the script crashes.
echo ======================================================
echo.
cmd /k powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0xiyu-login-diag.ps1"
