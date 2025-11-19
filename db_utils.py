# db_utils.py
import streamlit as st
import psycopg2
import pandas as pd
from contextlib import contextmanager


# Ця функція залишається для кешування самого об'єкта підключення
@st.cache_resource
def init_connection_pool():
    # Використовуємо пул з'єднань для кращої стабільності
    from psycopg2 import pool
    connection_pool = pool.SimpleConnectionPool(
        1, 20,  # min, max connections
        dbname=st.secrets["postgres"]["dbname"],
        user=st.secrets["postgres"]["user"],
        password=st.secrets["postgres"]["password"],
        host=st.secrets["postgres"]["host"],
        port=st.secrets["postgres"]["port"]
    )
    return connection_pool


# Створюємо контекстний менеджер для управління транзакціями
@contextmanager
def get_db_connection():
    """Отримує з'єднання з пулу і управляє транзакцією."""
    pool = init_connection_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def run_query(query, params=None, fetch=None):
    """
    Виконує SQL-запит у своїй власній транзакції.
    fetch: "one", "all", or None (для INSERT/UPDATE/DELETE)
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)

                if fetch == "one":
                    result = cur.fetchone()
                    conn.commit()  # Завершуємо транзакцію навіть для SELECT
                    return result

                if fetch == "all":
                    result = cur.fetchall()
                    columns = [desc[0] for desc in cur.description]
                    conn.commit()  # Завершуємо транзакцію навіть для SELECT
                    return pd.DataFrame(result, columns=columns)

                # Для INSERT, UPDATE, DELETE
                conn.commit()
                return None
    except psycopg2.Error as e:
        # Важливо! Якщо виникає помилка, ми її "ловимо" і повертаємо,
        # щоб вона не "зламала" все підключення.
        st.error(f"Помилка бази даних: {e}")
        return None  # Повертаємо None, щоб уникнути подальших помилок в коді