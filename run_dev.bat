@echo off
rem 开发/测试模式：直接运行源码（免打包）。改代码后关窗重跑即可。
cd /d "%~dp0"
chcp 65001 >nul
".\.venv\Scripts\python.exe" run.py
if errorlevel 1 pause