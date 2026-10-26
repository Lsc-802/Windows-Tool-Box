@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 确保用户级包目录可用（某些环境会注入 PYTHONNOUSERSITE=1）
set PYTHONNOUSERSITE=

set PYTHON=python
if exist "D:\Program Files\Python314\python.exe" set "PYTHON=D:\Program Files\Python314\python.exe"

"%PYTHON%" self_test.py
pause
