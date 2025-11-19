# pages/4_👥_Users.py
import streamlit as st
from db_utils import run_query, get_db_connection
import pandas as pd
import psycopg2
from faker import Faker
import time

st.set_page_config(page_title="Користувачі", layout="wide")
st.title("👥 Управління користувачами")


# --- ФУНКЦІЇ ДЛЯ РОБОТИ З ДАНИМИ ---
@st.cache_data
def load_users():
    """Завантажує всіх користувачів."""
    query = """
    SELECT 
        user_id, first_name, last_name, email, phone_number, registration_date
    FROM public."Users"
    ORDER BY user_id;
    """
    return run_query(query, fetch="all")


# Завантажуємо дані
users_df = load_users()
if users_df is None:
    st.error("Не вдалося завантажити дані про користувачів.")
    st.stop()

# --- БІЧНА ПАНЕЛЬ: ФІЛЬТРИ, СОРТУВАННЯ, ПОШУК ---
st.sidebar.header("Фільтри, сортування та пошук")

# Пошук
search_query = st.sidebar.text_input("Пошук (за email, ім'ям, прізвищем):")

# Сортування
sort_column = st.sidebar.selectbox(
    "Сортувати за:",
    options=["user_id", "first_name", "last_name", "email", "registration_date"],
    index=0  # Сортування за ID за замовчуванням
)
sort_ascending = st.sidebar.toggle("За зростанням", value=True)

# Застосування фільтрів та сортування
filtered_df = users_df.copy()
if search_query:
    # Шукаємо одночасно в кількох колонках
    mask = (
            filtered_df['first_name'].str.contains(search_query, case=False) |
            filtered_df['last_name'].str.contains(search_query, case=False) |
            filtered_df['email'].str.contains(search_query, case=False)
    )
    filtered_df = filtered_df[mask]

if not filtered_df.empty:
    filtered_df.sort_values(by=sort_column, ascending=sort_ascending, inplace=True)

st.dataframe(filtered_df, use_container_width=True)
st.info(f"Знайдено {len(filtered_df)} користувачів.")

if filtered_df.empty and not search_query:
    st.stop()

# --- CRUD ОПЕРАЦІЇ ---
st.header("CRUD Операції")
operation = st.selectbox("Оберіть операцію:", ["Створити (Реєстрація)", "Оновити", "Видалити"])

# === CREATE ===
if operation == "Створити (Реєстрація)":
    st.subheader("Реєстрація нового користувача")
    fake = Faker('uk_UA')
    with st.form("create_user_form", clear_on_submit=True):
        first_name = st.text_input("Ім'я")
        last_name = st.text_input("Прізвище")
        email = st.text_input("Email")
        phone = st.text_input("Номер телефону", value=fake.phone_number())
        password = st.text_input("Пароль (буде захешовано)", value=fake.password(), type="password")

        if st.form_submit_button("Зареєструвати"):
            if not all([first_name, last_name, email, phone, password]):
                st.error("Будь ласка, заповніть всі поля.")
            else:
                try:
                    # В реальному житті пароль треба хешувати, тут імітуємо
                    run_query(
                        'INSERT INTO public."Users" (first_name, last_name, email, phone_number, password_hash) VALUES (%s, %s, %s, %s, %s);',
                        (first_name, last_name, email, phone, f"hashed_{password}")
                    )
                    st.success(f"Користувача {first_name} {last_name} успішно зареєстровано!")
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                except psycopg2.Error as e:
                    st.error(f"Помилка бази даних: {e}")

# === UPDATE ===
elif operation == "Оновити":
    st.subheader("Оновити дані користувача")
    if not filtered_df.empty:
        user_to_update_id = st.selectbox("Оберіть ID користувача для оновлення:", options=filtered_df['user_id'])
        current_data = users_df[users_df['user_id'] == user_to_update_id].iloc[0]

        with st.form("update_user_form"):
            new_first_name = st.text_input("Ім'я", value=current_data['first_name'])
            new_last_name = st.text_input("Прізвище", value=current_data['last_name'])
            new_phone = st.text_input("Номер телефону", value=current_data['phone_number'])

            if st.form_submit_button("Оновити дані"):
                run_query(
                    'UPDATE public."Users" SET first_name = %s, last_name = %s, phone_number = %s WHERE user_id = %s;',
                    (new_first_name, new_last_name, new_phone, user_to_update_id)
                )
                st.success(f"Дані для користувача ID {user_to_update_id} оновлено!")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()

# === DELETE ===
elif operation == "Видалити":
    st.subheader("Видалити користувача")
    if not filtered_df.empty:
        user_to_delete_id = st.selectbox("Оберіть ID користувача для видалення:", options=filtered_df['user_id'])

        st.warning(
            f"Увага! Видалення користувача ID {user_to_delete_id} призведе до видалення (або відв'язки) всіх його оголошень, угод та автомобілів. Ця дія є незворотною.")

        if st.button("Я розумію, видалити користувача"):
            # Потрібно реалізувати складну логіку видалення, схожу на видалення автомобіля,
            # або налаштувати ON DELETE CASCADE/SET NULL в базі даних.
            # Для прикладу, використаємо SET NULL для owner_id в Cars.
            try:
                run_query('DELETE FROM public."Users" WHERE user_id = %s;', (user_to_delete_id,))
                st.success(f"Користувача ID {user_to_delete_id} видалено!")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()
            except psycopg2.Error as e:
                st.error(f"Помилка видалення: {e}. Перевірте залежності в базі даних.")