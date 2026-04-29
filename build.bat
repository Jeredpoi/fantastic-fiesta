@echo off
cd /d "%~dp0"
chcp 65001 >nul
echo ========================================
echo  LaserBoxMaker - сборка EXE
echo ========================================
echo.
python --version >/dev/null 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не найден. Установи Python с python.org
    pause
    exit /b 1
)
echo [1/2] Устанавливаю PyInstaller...
python -m pip install --upgrade pyinstaller --quiet
echo [2/2] Собираю EXE...
python -m PyInstaller --onefile --name LaserBoxMaker --hidden-import geometry --hidden-import dxf_writer app.py
echo.
if exist "dist\LaserBoxMaker.exe" (
    echo  Готово! Файл: dist\LaserBoxMaker.exe
    explorer dist
) else (
    echo  Что-то пошло не так. Смотри ошибки выше.
)
pause
