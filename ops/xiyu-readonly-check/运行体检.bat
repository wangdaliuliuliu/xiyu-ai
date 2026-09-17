@echo off
title DEPRECATED - use 3-diagnose-login.bat
echo.
echo ======================================================
echo   This launcher is DEPRECATED (old file name).
echo.
echo   Please use these instead:
echo.
echo     0-doctor.bat            (login doctor, on server side)
echo     1-test-connection.bat   (step 1: connection test)
echo     2-run-check.bat         (step 2: read-only check)
echo     3-diagnose-login.bat    (verbose SSH diagnosis)
echo.
echo   Starting the verbose diagnosis for you now...
echo ======================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0xiyu-login-diag.ps1"
