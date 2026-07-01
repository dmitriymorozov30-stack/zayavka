# Скрипт развёртывания Сервиса Заявок
# Стройсервис - IT-стандарт

$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "Развертывание Сервиса Заявок"

# Цвета для вывода
function Write-Step($text) { Write-Host "`n[$text]" -ForegroundColor Cyan }
function Write-OK($text) { Write-Host "[OK] $text" -ForegroundColor Green }
function Write-Err($text) { Write-Host "[ОШИБКА] $text" -ForegroundColor Red }
function Write-Warn($text) { Write-Host "[!] $text" -ForegroundColor Yellow }
function Write-Info($text) { Write-Host "[i] $text" -ForegroundColor Gray }

Write-Host ""
Write-Host "г==========================================================¬" -ForegroundColor Cyan
Write-Host "¦   Развертывание системы Сервис заявок 2.1                ¦" -ForegroundColor Cyan
Write-Host "¦   Стройсервис - IT-стандарт                              ¦" -ForegroundColor Cyan
Write-Host "L==========================================================-" -ForegroundColor Cyan
Write-Host ""

# ============================================
# ШАГ 1: ПРОВЕРКА И УСТАНОВКА PYTHON
# ============================================
Write-Step "1/8 Проверка Python..."

$pythonInstalled = $false
$pythonPath = $null

# Проверяем разные варианты установки Python
$pythonCommands = @("python", "python3", "py")
foreach ($cmd in $pythonCommands) {
    try {
        $version = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $pythonPath = $cmd
            $pythonInstalled = $true
            Write-OK "Python найден: $version"
            break
        }
    } catch {}
}

# Если Python не найден - устанавливаем
if (-not $pythonInstalled) {
    Write-Warn "Python не найден. Начинаю автоматическую установку..."
    
    # Метод 1: winget
    try {
        Write-Info "Попытка 1: Установка через winget..."
        $wingetPath = Get-Command winget -ErrorAction SilentlyContinue
        if ($wingetPath) {
            & winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements --silent 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-OK "Python установлен через winget"
                $pythonInstalled = $true
            }
        }
    } catch {
        Write-Info "winget недоступен"
    }
    
    # Метод 2: Прямое скачивание
    if (-not $pythonInstalled) {
        try {
            Write-Info "Попытка 2: Скачивание инсталлятора Python 3.11.9..."
            $pythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
            $installerPath = Join-Path $env:TEMP "python_installer.exe"
            
            # Скачиваем
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $webClient = New-Object System.Net.WebClient
            $webClient.DownloadFile($pythonUrl, $installerPath)
            Write-OK "Инсталлятор скачан"
            
            # Устанавливаем тихо
            Write-Info "Установка Python (тихий режим)..."
            $installArgs = "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_launcher=1 AssociateFiles=1"
            $process = Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -PassThru
            
            if ($process.ExitCode -eq 0) {
                Write-OK "Python установлен"
                $pythonInstalled = $true
                
                # Обновляем PATH
                $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
                
                # Ищем Python
                $possiblePaths = @(
                    "C:\Program Files\Python311\python.exe",
                    "C:\Python311\python.exe",
                    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
                )
                
                foreach ($path in $possiblePaths) {
                    if (Test-Path $path) {
                        $pythonPath = $path
                        break
                    }
                }
            } else {
                Write-Err "Установка Python не удалась (код: $($process.ExitCode))"
            }
            
            # Удаляем инсталлятор
            Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
            
        } catch {
            Write-Err "Не удалось установить Python: $_"
            Write-Info "Скачайте вручную: https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
            Read-Host "Нажмите Enter для выхода"
            exit 1
        }
    }
    
    # Финальная проверка
    if ($pythonInstalled) {
        Start-Sleep -Seconds 2
        try {
            $version = & $pythonPath --version 2>&1
            Write-OK "Python работает: $version"
        } catch {
            Write-Err "Python установлен, но не запускается. Перезапустите скрипт."
            Read-Host "Нажмите Enter для выхода"
            exit 1
        }
    }
}

# ============================================
# ШАГ 2: СОЗДАНИЕ СТРУКТУРЫ ПАПОК
# ============================================
Write-Step "2/8 Создание структуры папок..."
$folders = @("app", "static", "backups")
foreach ($folder in $folders) {
    if (-not (Test-Path $folder)) {
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
    }
}
Write-OK "Структура создана"

# ============================================
# ШАГ 3: СОЗДАНИЕ VENV
# ============================================
Write-Step "3/8 Создание виртуального окружения..."
if (Test-Path "venv") {
    Write-Warn "venv уже существует, пропускаем"
} else {
    try {
        & $pythonPath -m venv venv 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-OK "venv создан"
        } else {
            Write-Err "Не удалось создать venv"
            Read-Host "Нажмите Enter для выхода"
            exit 1
        }
    } catch {
        Write-Err "Ошибка создания venv: $_"
        Read-Host "Нажмите Enter для выхода"
        exit 1
    }
}

# ============================================
# ШАГ 4: УСТАНОВКА ЗАВИСИМОСТЕЙ
# ============================================
Write-Step "4/8 Установка зависимостей..."
if (-not (Test-Path "requirements.txt")) {
    Write-Err "requirements.txt не найден!"
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

$venvPython = ".\venv\Scripts\python.exe"
$venvPip = ".\venv\Scripts\pip.exe"

try {
    Write-Info "Обновление pip..."
    & $venvPython -m pip install --upgrade pip 2>&1 | Out-Null
    
    Write-Info "Установка зависимостей..."
    & $venvPip install -r requirements.txt
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Зависимости установлены"
    } else {
        Write-Err "Не удалось установить зависимости"
        Read-Host "Нажмите Enter для выхода"
        exit 1
    }
} catch {
    Write-Err "Ошибка установки: $_"
    Read-Host "Нажмите Enter для выхода"
    exit 1
}

# ============================================
# ШАГ 5: ГЕНЕРАЦИЯ JWT_SECRET
# ============================================
Write-Step "5/8 Генерация секретного ключа JWT..."
try {
    $jwtSecret = & $venvPython -c "import secrets; print(secrets.token_urlsafe(48))"
    if ($jwtSecret) {
        Write-OK "JWT_SECRET сгенерирован автоматически"
    } else {
        $jwtSecret = "fallback-secret-key-change-in-production-1234567890"
        Write-Warn "Не удалось сгенерировать, используем шаблон"
    }
} catch {
    $jwtSecret = "fallback-secret-key-change-in-production-1234567890"
    Write-Warn "Не удалось сгенерировать, используем шаблон"
}

# ============================================
# ШАГ 6: СОЗДАНИЕ .env
# ============================================
Write-Step "6/8 Проверка конфигурации .env..."
if (Test-Path ".env") {
    Write-Warn ".env уже существует, пропускаем"
} else {
    Write-Warn ".env не найден! Создаём с автоматическим JWT_SECRET..."
    
    $envContent = @"
# === БАЗА ДАННЫХ ===
DATABASE_URL=sqlite+aiosqlite:///./zayavka.db

# === JWT (БЕЗОПАСНОСТЬ) ===
JWT_SECRET=$jwtSecret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480

# === SMTP (ПОЧТА) ===
SMTP_SERVER=mail-01
SMTP_PORT=25
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=support@stroisservis.ru
SMTP_USE_TLS=false
SMTP_START_TLS=false

# === СЕРВЕР ===
PORT=8000
"@
    
    $envContent | Out-File -FilePath ".env" -Encoding UTF8
    Write-Host ""
    Write-Host "г==========================================================¬" -ForegroundColor Yellow
    Write-Host "¦  [!] Файл .env создан с АВТОМАТИЧЕСКИМ JWT_SECRET        ¦" -ForegroundColor Yellow
    Write-Host "L==========================================================-" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "ВАЖНО: Отредактируйте .env и укажите:" -ForegroundColor Yellow
    Write-Host "  - SMTP_SERVER, SMTP_USER, SMTP_PASSWORD" -ForegroundColor Yellow
}

# ============================================
# ШАГ 7: ПРОВЕРКА ФАЙЛОВ
# ============================================
Write-Step "7/8 Проверка файлов проекта..."
$requiredFiles = @(
    "app\main.py",
    "app\routes.py",
    "app\models.py",
    "app\auth.py",
    "app\notifications.py",
    "app\database.py",
    "app\__init__.py",
    "static\index.html",
    "run.py"
)

$missing = @()
foreach ($file in $requiredFiles) {
    if (-not (Test-Path $file)) {
        $missing += $file
        Write-Err $file
    }
}

if ($missing.Count -gt 0) {
    Write-Err "Отсутствуют важные файлы!"
    Read-Host "Нажмите Enter для выхода"
    exit 1
}
Write-OK "Все файлы на месте"

# ============================================
# ШАГ 8: ОТКРЫТИЕ ПОРТА В БРАНДМАУЭРЕ
# ============================================
Write-Step "8/8 Открытие порта 8000 в брандмауэре..."
try {
    $existingRule = Get-NetFirewallRule -DisplayName "Zayavka HTTP (8000)" -ErrorAction SilentlyContinue
    if ($existingRule) {
        Write-OK "Порт 8000 уже открыт"
    } else {
        New-NetFirewallRule -DisplayName "Zayavka HTTP (8000)" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -ErrorAction Stop | Out-Null
        Write-OK "Порт 8000 открыт в брандмауэре"
    }
} catch {
    Write-Warn "Не удалось открыть порт автоматически"
    Write-Info "Запустите от имени администратора или вручную:"
    Write-Info 'New-NetFirewallRule -DisplayName "Zayavka HTTP (8000)" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow'
}

# ============================================
# СОЗДАНИЕ ЯРЛЫКОВ
# ============================================
Write-Step "Создание ярлыков запуска..."

# start_server.bat
$startBat = @"
@echo off
chcp 1251 >nul
cd /d "%~dp0"
call venv\Scripts\activate.bat
python run.py
pause
"@
$startBat | Out-File -FilePath "start_server.bat" -Encoding ASCII

# stop_server.bat
$stopBat = @"
@echo off
chcp 1251 >nul
echo Остановка сервера...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *run*" >nul 2>&1
echo [OK] Сервер остановлен
pause
"@
$stopBat | Out-File -FilePath "stop_server.bat" -Encoding ASCII

Write-OK "Ярлыки созданы: start_server.bat, stop_server.bat"

# ============================================
# ГОТОВО
# ============================================
Write-Host ""
Write-Host "г==========================================================¬" -ForegroundColor Green
Write-Host "¦   [OK] РАЗВЕРТЫВАНИЕ ЗАВЕРШЕНО УСПЕШНО!                  ¦" -ForegroundColor Green
Write-Host "L==========================================================-" -ForegroundColor Green
Write-Host ""
Write-Host "Следующие шаги:" -ForegroundColor Cyan
Write-Host "  1. Отредактируйте .env (SMTP настройки)" -ForegroundColor White
Write-Host "  2. Запустите сервер двойным кликом на:" -ForegroundColor White
Write-Host "     start_server.bat" -ForegroundColor Yellow
Write-Host "  3. Откройте: http://localhost:8000" -ForegroundColor White
Write-Host "  4. Зарегистрируйте первого руководителя" -ForegroundColor White
Write-Host ""
Write-Info "Бэкапы создаются автоматически (раз в 3 дня)"
Write-Info "Публичный адрес определяется автоматически через ipconfig | nslookup"
Write-Host ""
Read-Host "Нажмите Enter для выхода"