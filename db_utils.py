import psycopg2
import streamlit as st
import pandas as pd
from config import DB_ROLES  # Імпортуємо словник ролей


def get_db_connection():
    """
    Створює з'єднання з БД, використовуючи роль поточного користувача.
    """
    # 1. Визначаємо роль
    # Якщо ми в Streamlit і користувач залогінений -> беремо його роль
    # Якщо ні (наприклад, екран логіну або скрипт) -> беремо 'default' (адмінський доступ)
    role_key = 'default'

    try:
        if hasattr(st, 'session_state') and 'role' in st.session_state and st.session_state['role']:
            role_key = st.session_state['role']  # 'client', 'manager', 'admin'
    except:
        pass  # Ми не в Streamlit, використовуємо default

    # 2. Беремо конфіг для цієї ролі
    config = DB_ROLES.get(role_key, DB_ROLES['default'])

    # 3. Підключаємось
    return psycopg2.connect(**config)


def run_query(query, params=None, fetch="none", commit=False):
    conn = None
    try:
        conn = get_db_connection()  # <--- Тут тепер магія вибору ролі
        cur = conn.cursor()
        cur.execute(query, params)

        if commit:
            conn.commit()

        result = None
        if fetch == "all":
            data = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            result = pd.DataFrame(data, columns=columns)
        elif fetch == "one":
            result = cur.fetchone()

        cur.close()
        return result

    except psycopg2.errors.InsufficientPrivilege:
        # Спеціальна обробка помилки прав доступу
        st.error("⛔ ПОМИЛКА БЕЗПЕКИ СУБД: У вашої ролі немає прав на виконання цієї дії!")
        if conn: conn.rollback()
        return None

    except Exception as e:
        if conn: conn.rollback()
        st.error(f"Помилка: {e}")
        return None
    finally:
        if conn: conn.close()


# Функція логування (завжди пише від імені менеджера або адміна,
# або можна дати права на INSERT в Audit_Logs всім)
def log_action(user_id, action_type, table_name, record_id, details):
    conn = None
    try:
        # Для логів краще брати дефолтне (адмінське) з'єднання, щоб права не заважали аудиту
        conn = psycopg2.connect(**DB_ROLES['default'])
        cur = conn.cursor()
        query = """
            INSERT INTO "Audit_Logs" (user_id, action_type, table_name, record_id, details)
            VALUES (%s, %s, %s, %s, %s);
        """
        cur.execute(query, (user_id, action_type, table_name, record_id, details))
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Audit Error: {e}")
    finally:
        if conn: conn.close()