@echo off
REM Windows 打包脚本 - 在 Windows 上双击运行
setlocal

where python >nul 2>nul
if errorlevel 1 (
    echo [x] 未检测到 Python, 请先安装 Python 3.10+
    pause
    exit /b 1
)

echo [1/3] 安装依赖...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo [2/3] 打包...
pyinstaller --noconfirm --noconsole --onefile --name FpBrowser main.py

echo [3/3] 完成. EXE 在 dist\FpBrowser.exe
echo.
dir dist
pause
