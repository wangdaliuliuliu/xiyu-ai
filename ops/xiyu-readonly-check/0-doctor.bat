@echo off
title Xiyu check - STEP 0 login doctor
echo.
echo ======================================================
echo   STEP 0 : login doctor
echo.
echo   Use this when the key login fails.
echo   Read-only: nothing is changed.
echo.
echo   This window STAYS OPEN even if the script crashes.
echo ======================================================
echo.
cmd /k powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0xiyu-check.ps1" -Mode doctor
