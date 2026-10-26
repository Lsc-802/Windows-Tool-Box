@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 确保用户级包目录可用（某些环境会注入 PYTHONNOUSERSITE=1）
set PYTHONNOUSERSITE=

set PY=python
if exist "D:\Program Files\Python314\python.exe" set "PY=D:\Program Files\Python314\python.exe"

echo ============================================
echo  Windows Tool Box · 一键打包
echo  产物：dist\WindowsToolBox.exe （约 1-2 分钟）
echo ============================================
"%PY%" -m PyInstaller --noconfirm --onefile --windowed ^
    --name WindowsToolBox --icon icon.ico ^
    --hidden-import wmi --hidden-import win32com.client ^
    --hidden-import pythoncom --hidden-import pywintypes ^
    main.py

if errorlevel 1 (
    echo.
    echo [失败] 打包出错，请查看上方日志。
    pause
    exit /b 1
)
echo.
echo [完成] 双击 dist\WindowsToolBox.exe 即可使用。
pause
