# pages/5_🧑‍💼_Employees.py
import streamlit as st
from db_utils import run_query, get_db_connection
import pandas as pd
import psycopg2
from faker import Faker
import time

st.set_page_config(page_title="Співробітники", layout="wide")
st.title("🧑‍💼 Управління співробітниками")


# --- ФУНКЦІЇ ДЛЯ РОБОТИ З ДАНИМИ ---
@st.cache_data
def load_employees_and_positions():
    """Завантажує співробітників та довідник посад."""
    employees_query = """
    SELECT
        e.employee_id, e.first_name, e.last_name, p.name AS position,
        e.email, e.is_active
    FROM public."Employees" e
    JOIN public."Positions" p ON e.position_id = p.position_id
    ORDER BY e.employee_id;
    """
    employees = run_query(employees_query, fetch="all")

    positions_query = 'SELECT position_id, name FROM public."Positions";'
    positions = run_query(positions_query, fetch="all")

    return employees, positions


# Завантажуємо дані
employees_df, positions_df = load_employees_and_positions()
if employees_df is None or positions_df is None:
    st.error("Не вдалося завантажити дані про співробітників.")
    st.stop()

# --- БІЧНА ПАНЕЛЬ: ФІЛЬТРИ, СОРТУВАННЯ, ПОШУК ---
st.sidebar.header("Фільтри, сортування та пошук")

# Пошук
search_query = st.sidebar.text_input("Пошук (за email, ім'ям, прізвищем):")

# Сортування
sort_column = st.sidebar.selectbox(
    "Сортувати за:",
    options=["employee_id", "first_name", "last_name", "position", "email"],
)
sort_ascending = st.sidebar.toggle("За зростанням ", value=True)  # Пробіл в кінці для унікального ключа

# Застосування фільтрів та сортування
filtered_df = employees_df.copy()
if search_query:
    mask = (
            filtered_df['first_name'].str.contains(search_query, case=False) |
            filtered_df['last_name'].str.contains(search_query, case=False) |
            filtered_df['email'].str.contains(search_query, case=False)
    )
    filtered_df = filtered_df[mask]

if not filtered_df.empty:
    filtered_df.sort_values(by=sort_column, ascending=sort_ascending, inplace=True)

st.dataframe(filtered_df, use_container_width=True)
st.info(f"Знайдено {len(filtered_df)} співробітників.")

if filtered_df.empty and not search_query:
    st.stop()

# --- CRUD ОПЕРАЦІЇ ---
st.header("CRUD Операції")
operation = st.selectbox("Оберіть операцію:", ["Додати співробітника", "Оновити дані", "Видалити співробітника"])

# === CREATE ===
if operation == "Додати співробітника":
    st.subheader("Додавання нового співробітника")
    fake = Faker('uk_UA')
    with st.form("create_employee_form", clear_on_submit=True):
        first_name = st.text_input("Ім'я")
        last_name = st.text_input("Прізвище")
        email = st.text_input("Email")
        position_id = st.selectbox(
            "Посада:",
            options=positions_df['position_id'],
            format_func=lambda x: positions_df.loc[positions_df['position_id'] == x, 'name'].iloc[0]
        )
        is_active = st.checkbox("Активний", value=True)

        if st.form_submit_button("Додати"):
            if not all([first_name, last_name, email]):
                st.error("Будь ласка, заповніть поля 'Ім'я', 'Прізвище' та 'Email'.")
            else:
                try:
                    run_query(
                        'INSERT INTO public."Employees" (first_name, last_name, position_id, email, is_active) VALUES (%s, %s, %s, %s, %s);',
                        (first_name, last_name, position_id, email, is_active)
                    )
                    st.success(f"Співробітника {first_name} {last_name} успішно додано!")
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                except psycopg2.Error as e:
                    st.error(f"Помилка бази даних: {e}")

# === UPDATE ===
elif operation == "Оновити дані":
    st.subheader("Оновити дані співробітника")
    emp_to_update_id = st.selectbox("Оберіть ID співробітника для оновлення:", options=filtered_df['employee_id'])
    current_data = employees_df[employees_df['employee_id'] == emp_to_update_id].iloc[0]

    with st.form("update_employee_form"):
        current_pos_id = positions_df[positions_df['name'] == current_data['position']].iloc[0]['position_id']

        new_email = st.text_input("Email", value=current_data['email'])
        new_position_id = st.selectbox(
            "Посада:",
            options=positions_df['position_id'],
            index=list(positions_df['position_id']).index(current_pos_id),  # Встановлюємо поточну посаду
            format_func=lambda x: positions_df.loc[positions_df['position_id'] == x, 'name'].iloc[0]
        )
        new_is_active = st.checkbox("Активний", value=current_data['is_active'])

        if st.form_submit_button("Оновити"):
            run_query(
                'UPDATE public."Employees" SET email = %s, position_id = %s, is_active = %s WHERE employee_id = %s;',
                (new_email, new_position_id, new_is_active, emp_to_update_id)
            )
            st.success(f"Дані для співробітника ID {emp_to_update_id} оновлено!")
            st.cache_data.clear()
            time.sleep(1)
            st.rerun()

# === DELETE ===
elif operation == "Видалити співробітника":
    st.subheader("Видалити співробітника")
    emp_to_delete_id = st.selectbox("Оберіть ID співробітника для видалення:", options=filtered_df['employee_id'])

    st.warning(
        f"Увага! Співробітник ID {emp_to_delete_id} буде видалений. Це може вплинути на історичні дані в заявках та інспекціях.")

    if st.button("Видалити"):
        try:
            # В базі для manager_id та inspector_id має стояти ON DELETE SET NULL, щоб це працювало
            run_query('DELETE FROM public."Employees" WHERE employee_id = %s;', (emp_to_delete_id,))
            st.success(f"Співробітника ID {emp_to_delete_id} видалено!")
            st.cache_data.clear()
            time.sleep(1)
            st.rerun()
        except psycopg2.Error as e:
            st.error(f"Помилка видалення: {e}. Перевірте, чи не призначений цей співробітник на активні заявки.")