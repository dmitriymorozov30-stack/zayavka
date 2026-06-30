import os, signal, sys, psutil, sqlite3, shutil, datetime, glob, subprocess, re
import uvicorn
from dotenv import load_dotenv

load_dotenv()
DB_PATH = "zayavka.db"
BACKUP_DIR = "backups"
MAX_BACKUPS = 3
BACKUP_INTERVAL_DAYS = 3

def get_public_hostname() -> str:
    """Определяет DNS-имя сервера через ipconfig + nslookup"""
    try:
        # 1. Получаем IPv4 через ipconfig
        result = subprocess.run(
            ['ipconfig'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        # Ищем IPv4-адрес (первый подходящий)
        ip_match = re.search(r'IPv4.*?(\d+\.\d+\.\d+\.\d+)', result.stdout)
        if not ip_match:
            print("⚠️ Не удалось определить IPv4, используем localhost")
            return "localhost"
        
        ip = ip_match.group(1)
        print(f"🔍 Найден IPv4: {ip}")
        
        # 2. Делаем nslookup для получения DNS-имени
        result = subprocess.run(
            ['nslookup', ip],
            capture_output=True,
            text=True,
            encoding='cp866',  # Windows использует cp866 для консоли
            errors='ignore'
        )
        
        # Ищем строку "Name:    hostname.domain"
        name_match = re.search(r'Name:\s+(\S+)', result.stdout)
        if name_match:
            full_hostname = name_match.group(1)
            # Убираем доменную часть, оставляем только имя
            hostname = full_hostname.split('.')[0]
            print(f"✅ DNS-имя сервера: {hostname}")
            return hostname
        
        # Если nslookup не нашёл имя — используем IP
        print(f"⚠️ DNS-имя не найдено, используем IP: {ip}")
        return ip
        
    except Exception as e:
        print(f"⚠️ Ошибка определения hostname: {e}")
        return "localhost"

def cleanup_db():
    if not os.path.exists(DB_PATH): return
    print(f"🔄 Проверка блокировки {DB_PATH}...")
    for proc in psutil.process_iter(['pid', 'name', 'open_files']):
        try:
            if proc.info['open_files']:
                for f in proc.info['open_files']:
                    if f.path and DB_PATH in f.path:
                        print(f"🔒 Найден процесс {proc.info['pid']}, убиваем...")
                        proc.kill()
                        proc.wait(timeout=3)
                        print(f"✅ Процесс {proc.info['pid']} завершён")
                        return
        except: pass

def migrate_db():
    if not os.path.exists(DB_PATH): return
    print("🔧 Проверка миграции БД...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(requests)")
    columns = [row[1] for row in cursor.fetchall()]
    
    migrations = [
        ("estimated_cost", "REAL"),
        ("director_cost", "REAL"),
        ("executor_id", "INTEGER"),
    ]
    
    for col_name, col_type in migrations:
        if col_name not in columns:
            print(f"  ➕ Добавляю поле {col_name}...")
            cursor.execute(f"ALTER TABLE requests ADD COLUMN {col_name} {col_type}")
    
    conn.commit()
    conn.close()
    print("✅ Миграция завершена")

def create_backup():
    if not os.path.exists(DB_PATH):
        print("⚠️ БД не найдена, бэкап пропущен")
        return False
    
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"zayavka_backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    
    try:
        shutil.copy2(DB_PATH, backup_path)
        size = os.path.getsize(backup_path)
        print(f"✅ Бэкап создан: {backup_path} ({size} байт)")
        return True
    except Exception as e:
        print(f"❌ Ошибка бэкапа: {e}")
        return False

def cleanup_old_backups():
    pattern = os.path.join(BACKUP_DIR, "zayavka_backup_*.db")
    backups = sorted(glob.glob(pattern))
    
    if len(backups) > MAX_BACKUPS:
        to_delete = backups[:-MAX_BACKUPS]
        for f in to_delete:
            try:
                os.remove(f)
                print(f"🗑️ Удалён старый бэкап: {os.path.basename(f)}")
            except Exception as e:
                print(f"⚠️ Не удалось удалить {f}: {e}")

def check_and_backup():
    print("📦 Проверка необходимости бэкапа...")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    pattern = os.path.join(BACKUP_DIR, "zayavka_backup_*.db")
    backups = sorted(glob.glob(pattern))
    
    if not backups:
        print("📦 Бэкапов нет, создаём первый...")
        create_backup()
        return
    
    last_backup = backups[-1]
    last_backup_time = datetime.datetime.fromtimestamp(os.path.getmtime(last_backup))
    days_since_backup = (datetime.datetime.now() - last_backup_time).days
    
    if days_since_backup >= BACKUP_INTERVAL_DAYS:
        print(f"📦 Прошло {days_since_backup} дней, создаём бэкап...")
        if create_backup():
            cleanup_old_backups()
    else:
        print(f"✅ Последний бэкап был {days_since_backup} дней назад, пропускаем")

def shutdown_handler(signum, frame):
    print("\n🛑 Остановка сервера...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    # ✅ ОПРЕДЕЛЯЕМ DNS-ИМЯ СЕРВЕРА
    public_host = get_public_hostname()
    os.environ['PUBLIC_HOST'] = public_host  # Передаём в приложение
    
    cleanup_db()
    migrate_db()
    check_and_backup()
    
    port = int(os.getenv("PORT", "8000"))
    
    print("\n" + "=" * 60)
    print(f"🌐 ПУБЛИЧНЫЙ АДРЕС СИСТЕМЫ: http://{public_host}:{port}")
    print(f"📧 Письма будут содержать ссылку: http://{public_host}:{port}")
    print("=" * 60 + "\n")
    
    print(f"🚀 Запуск FastAPI сервера на порту {port}...")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)