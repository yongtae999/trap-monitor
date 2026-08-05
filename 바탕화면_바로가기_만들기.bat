@echo off
chcp 65001 > nul
echo Creating desktop shortcut...

set SCRIPT_DIR=%~dp0
set SHORTCUT=%USERPROFILE%\Desktop\TrapMonitor.lnk

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%SCRIPT_DIR%실행.bat'; $s.WorkingDirectory = '%SCRIPT_DIR%'; $s.IconLocation = '%SystemRoot%\System32\shell32.dll,23'; $s.Description = 'Illegal Trap Monitor'; $s.Save()"

if exist "%SHORTCUT%" (
    echo.
    echo  Done! "TrapMonitor" shortcut created on Desktop.
) else (
    echo.
    echo  Failed. Please copy 실행.bat directly to the Desktop.
)

echo.
pause
