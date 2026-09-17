@echo off
title DEPRECATED - use 1-test-connection.bat
echo.
echo ======================================================
echo   This launcher is DEPRECATED (old file name).
echo.
echo   Please use these instead:
echo.
echo     0-doctor.bat            (login doctor)
echo     1-test-connection.bat   (step 1: connection test)
echo     2-run-check.bat         (step 2: read-only check)
echo.
echo   Starting the connection test for you now...
echo ======================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0xiyu-check.ps1" -Mode test
