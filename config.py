# config.py

# Базові налаштування
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "CarMarketplace"

# Словник ролей
DB_ROLES = {
    "client": {
        "dbname": DB_NAME,
        "user": "db_client",
        "password": "client_pass",  # Перевір, чи тут твій пароль з SQL
        "host": DB_HOST,
        "port": DB_PORT
    },

    "manager": {
        "dbname": DB_NAME,
        "user": "db_manager",
        "password": "manager_pass",  # Перевір пароль
        "host": DB_HOST,
        "port": DB_PORT
    },

    "admin": {
        "dbname": DB_NAME,
        "user": "db_admin",
        "password": "admin_pass",  # Перевір пароль
        "host": DB_HOST,
        "port": DB_PORT
    },

    "default": {
        "dbname": DB_NAME,
        "user": "db_admin",  # API працює від імені адміна
        "password": "admin_pass",  # Перевір пароль
        "host": DB_HOST,
        "port": DB_PORT
    }
}

# --- ВАЖЛИВО: СУМІСНІСТЬ ДЛЯ API ---
DB_CONFIG = DB_ROLES['default']