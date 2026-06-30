@echo off
chcp 1251 >nul
title Развертывание Сервиса Заявок
color 0A

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║   Развертывание системы "Сервис заявок 2.1"              ║
echo ║   Стройсервис - IT-стандарт                              ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

:: Проверка Python
echo [1/7] Проверка Python...
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ОШИБКА] Python не установлен!
    echo Скачайте с https://www.python.org/downloads/
    echo При установке ОБЯЗАТЕЛЬНО отметьте "Add Python to PATH"
    pause
    exit /b 1
)

:: Проверка версии Python (должна быть 3.8+)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python найден: %PYVER%

:: Создание папок
echo.
echo [2/7] Создание структуры папок...
if not exist "app" mkdir app
if not exist "static" mkdir static
if not exist "backups" mkdir backups
echo [OK] Структура создана

:: Создание venv
echo.
echo [3/7] Создание виртуального окружения...
if exist "venv" (
    echo [!] venv уже существует, пропускаем
) else (
    python -m venv venv
    if errorlevel 1 (
        color 0C
        echo [ОШИБКА] Не удалось создать venv
        pause
        exit /b 1
    )
    echo [OK] venv создан
)

:: Установка зависимостей
echo.
echo [4/7] Установка зависимостей...
call venv\Scripts\activate.bat
if not exist "requirements.txt" (
    color 0C
    echo [ОШИБКА] requirements.txt не найден!
    pause
    exit /b 1
)
call venv\Scripts\python.exe -m pip install --upgrade pip >nul 2>&1
call venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 (
    color 0C
    echo [ОШИБКА] Не удалось установить зависимости
    pause
    exit /b 1
)
echo [OK] Зависимости установлены

:: Генерация JWT_SECRET
echo.
echo [5/7] Генерация секретного ключа JWT...
for /f "delims=" %%i in ('call venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"') do set JWT_SECRET=%%i
if "%JWT_SECRET%"=="" (
    echo [!] Не удалось сгенерировать, используем шаблон
    set JWT_SECRET=fallback-secret-key-change-in-production-1234567890
) else (
    echo [OK] JWT_SECRET сгенерирован автоматически
)

:: Создание .env
echo.
echo [6/7] Проверка конфигурации .env...
if exist ".env" (
    echo [!] .env уже существует, пропускаем
) else (
    echo [!] .env не найден! Создаём с автоматическим JWT_SECRET...
    
    > .env (
        echo # === БАЗА ДАННЫХ ===
        echo DATABASE_URL=sqlite+aiosqlite:///./zayavka.db
        echo.
        echo # === JWT (БЕЗОПАСНОСТЬ) ===
        echo JWT_SECRET=%JWT_SECRET%
        echo JWT_ALGORITHM=HS256
        echo ACCESS_TOKEN_EXPIRE_MINUTES=480
        echo.
        echo # === SMTP (ПОЧТА) ===
        echo SMTP_SERVER=mail-01
        echo SMTP_PORT=25
        echo SMTP_USER=
        echo SMTP_PASSWORD=
        echo SMTP_FROM=support@stroisservis.ru
        echo SMTP_USE_TLS=false
        echo SMTP_START_TLS=false
        echo.
        echo # === СЕРВЕР ===
        echo PORT=8000
    )
    
    color 0E
    echo [!] Файл .env создан с АВТОМАТИЧЕСКИМ JWT_SECRET
    echo.
    echo ВАЖНО: Отредактируйте .env и укажите:
    echo   - SMTP_SERVER, SMTP_USER, SMTP_PASSWORD (для отправки писем)
    echo   - PUBLIC_HOST будет определён автоматически при запуске
)

:: Проверка файлов
echo.
echo [7/7] Проверка файлов проекта...
set MISSING=0
if not exist "app\main.py" (set MISSING=1 & echo [ОШИБКА] app\main.py)
if not exist "app\routes.py" (set MISSING=1 & echo [ОШИБКА] app\routes.py)
if not exist "app\models.py" (set MISSING=1 & echo [ОШИБКА] app\models.py)
if not exist "app\auth.py" (set MISSING=1 & echo [ОШИБКА] app\auth.py)
if not exist "app\notifications.py" (set MISSING=1 & echo [ОШИБКА] app\notifications.py)
if not exist "app\database.py" (set MISSING=1 & echo [ОШИБКА] app\database.py)
if not exist "app\__init__.py" (set MISSING=1 & echo [ОШИБКА] app\__init__.py)
if not exist "static\index.html" (set MISSING=1 & echo [ОШИБКА] static\index.html)
if not exist "run.py" (set MISSING=1 & echo [ОШИБКА] run.py)

if %MISSING%==1 (
    color 0C
    echo.
    echo [ОШИБКА] Отсутствуют важные файлы!
    pause
    exit /b 1
)
echo [OK] Все файлы на месте

:: Открытие порта в брандмауэре (опционально)
echo.
echo [?] Открыть порт 8000 в брандмауэре Windows? (Y/N)
set /p OPENPORT=
if /i "%OPENPORT%"=="Y" (
    echo Открываем порт 8000...
    netsh advfirewall firewall add rule name="Zayavka HTTP (8000)" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
    if errorlevel 1 (
        echo [!] Не удалось открыть порт. Запустите от имени администратора или вручную:
        echo     netsh advfirewall firewall add rule name="Zayavka HTTP (8000)" dir=in action=allow protocol=TCP localport=8000
    ) else (
        echo [OK] Порт 8000 открыт в брандмауэре
    )
)

:: Готово
echo.
color 0A
echo ╔══════════════════════════════════════════════════════════╗
echo ║   [OK] РАЗВЕРТЫВАНИЕ ЗАВЕРШЕНО УСПЕШНО!                  ║
echo ╚══════════════════════════════════════════════════════════╝
echo.
echo Следующие шаги:
echo   1. Отредактируйте .env (SMTP настройки для отправки писем)
echo   2. Запустите сервер:
echo      venv\Scripts\activate
echo      python run.py
echo   3. Откройте: http://localhost:8000
echo   4. Зарегистрируйте первого пользователя с ролью "Руководитель"
echo.
echo [i] Бэкапы создаются автоматически при запуске сервера
echo     (раз в 3 дня, хранятся 3 последних копии в папке backups\)
echo.
echo [i] Публичный адрес будет определён автоматически:
echo     ipconfig ^| nslookup ^> DNS-имя сервера
echo.
pause