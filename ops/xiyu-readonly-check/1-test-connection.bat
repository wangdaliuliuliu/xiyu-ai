@echo off
title Xiyu check - STEP 1 connection test
echo.
echo ======================================================
echo   STEP 1 of 2 : connection test
echo.
echo   Only tests whether this PC can log in.
echo   Reads no data, changes nothing.
echo.
echo   This window STAYS OPEN even if the script crashes.
echo ======================================================
echo.
cmd /k powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0xiyu-check.ps1" -Mode test
