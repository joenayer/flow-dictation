@echo off
setlocal
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0export_wispr_dictionary.py"
    goto done
)
where python >nul 2>nul
if not errorlevel 1 (
    python "%~dp0export_wispr_dictionary.py"
    goto done
)
echo Python 3 is required to make the transfer file. Nothing was changed.
:done
echo.
pause
endlocal
