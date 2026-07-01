@echo off
chcp 1251 >nul
title Развертывание Сервиса Заявок

:: Запуск PowerShell скрипта с обходом политики выполнения
powershell -ExecutionPolicy Bypass -File "%~dp0deploy.ps1"

:: Если PowerShell завершился с ошибкой - ждём нажатия клавиши
if errorlevel 1 (
    echo.
    echo [!] Развертывание завершилось с ошибкой
    pause
)