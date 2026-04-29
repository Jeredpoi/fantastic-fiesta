#!/usr/bin/env bash
set -e

echo "========================================"
echo " LaserBoxMaker - сборка бинарника"
echo "========================================"

if ! command -v python3 &>/dev/null; then
    echo "ОШИБКА: python3 не найден. Установи Python 3.9+"
    exit 1
fi

echo "[1/2] Устанавливаю PyInstaller..."
python3 -m pip install --upgrade pyinstaller --quiet

echo "[2/2] Собираю бинарник..."
python3 -m PyInstaller --onefile --windowed --name LaserBoxMaker app.py

echo ""
echo " Готово! Файл: dist/LaserBoxMaker"
