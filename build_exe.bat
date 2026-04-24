@echo off
chcp 65001 > nul
echo ============================================================
echo   iGPU 烤机程序 - Windows EXE 打包脚本
echo   使用 PyInstaller 打包为单文件 EXE
echo ============================================================
echo.

:: 检查 Python
python --version 2>nul
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python！请先安装 Python 3.9+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 安装依赖
echo [1/4] 安装 Python 依赖包...
pip install pyinstaller numpy psutil PyOpenGL PyOpenGL-accelerate glfw 2>nul
if %errorlevel% neq 0 (
    echo [警告] 部分包安装失败，将使用最小模式打包
)
echo.

:: 清理旧构建
echo [2/4] 清理旧构建文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist igpu_burn_win.spec del igpu_burn_win.spec
echo.

:: PyInstaller 打包
echo [3/4] 开始打包 EXE（可能需要 1-2 分钟）...
pyinstaller ^
    --onefile ^
    --console ^
    --name "igpu_burn_win" ^
    --icon NONE ^
    --add-data "." ^
    --hidden-import numpy ^
    --hidden-import psutil ^
    --collect-all numpy ^
    igpu_burn_win.py

if %errorlevel% neq 0 (
    echo [错误] 打包失败！
    pause
    exit /b 1
)

echo.
echo [4/4] 打包完成！
echo.
echo ============================================================
echo   输出文件: dist\igpu_burn_win.exe
echo.
echo   使用方法:
echo     dist\igpu_burn_win.exe               (默认模式)
echo     dist\igpu_burn_win.exe --info        (查看 GPU 信息)
echo     dist\igpu_burn_win.exe --streams 8   (8 路编码)
echo     dist\igpu_burn_win.exe --duration 300 (限时 300 秒)
echo ============================================================
echo.

:: 复制 FFmpeg 提示
echo [提示] 请将 ffmpeg.exe 放到 dist\ 目录下，或添加到系统 PATH
echo        下载地址: https://github.com/BtbN/FFmpeg-Builds/releases
echo.

pause
