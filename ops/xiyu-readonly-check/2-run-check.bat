@echo off
title Xiyu check - STEP 2 read-only check
echo.
echo ======================================================
echo   STEP 2 of 2 : read-only server check
echo.
echo   Every command is read-only.
echo   Nothing is modified, restarted or deleted.
echo   LIMI and capybara-game are never touched.
echo.
echo   This window STAYS OPEN even if the script crashes.
echo ======================================================
echo.
cmd /k powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0xiyu-check.ps1" -Mode full
