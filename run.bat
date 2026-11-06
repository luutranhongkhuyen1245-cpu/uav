@echo off
title Fire Detection Server
cd /d "%~dp0\fire_detection"
echo ========================================================
echo       Fire Detection System - Django & YOLO
echo ========================================================
echo Dang khoi dong may chu tai: http://127.0.0.1:8000
echo Nhan Ctrl+C de dung may chu.
echo ========================================================
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
pause

