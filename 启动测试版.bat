@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 确保用户级包目录可用（某些环境会注入 PYTHONNOUSERSITE=1）
set PYTHONNOUSERSITE=

rem 优先使用用户真实安装的 Python（避免命中微软商店占位符）
set PYTHON=pythonw
if exist "D:\Program Files\Python314\pythonw.exe" set "PYTHON=D:\Program Files\Python314\pythonw.exe"

start "" "%PYTHON%" main.py
