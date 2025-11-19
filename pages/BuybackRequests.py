import uuid

import streamlit as st
from db_utils import run_query, get_db_connection
import pandas as pd
import psycopg2
import time

st.set_page_config(page_title="Заявки на викуп", layout="wide")
st.title("📥 Заявки на викуп")


# --- ФУНКЦІЇ ДЛЯ РОБОТИ З ДАНИМИ ---
@st.cache_data
def load_all_buyback_data():
    """Завантажує всі заявки, а також дані для форм."""
    requests_query = """
    SELECT
        br.request_id, br.status,
        u.email AS user_email,
        b.name || ' ' || m.name || ' ' || c.year AS car_info,
        br.car_id,
        br.desired_price, br.offer_price,
        emp.first_name || ' ' || emp.last_name AS manager,
        br.request_date
    FROM public."Buyback_Requests" br
    JOIN public."Users" u ON br.user_id = u.user_id
    JOIN public."Cars" c ON br.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    LEFT JOIN public."Employees" emp ON br.manager_id = emp.employee_id
    ORDER BY br.request_date DESC;
    """
    requests = run_query(requests_query, fetch="all")

    # Дані для форм
    users = run_query('SELECT user_id, email FROM public."Users";', fetch="all")
    cars = run_query('SELECT car_id, vin_code FROM public."Cars";', fetch="all")
    employees = run_query('SELECT employee_id, first_name || \' \' || last_name as full_name FROM public."Employees";',
                          fetch="all")

    return requests, users, cars, employees


requests_df, users_df, cars_df, employees_df = load_all_buyback_data()
if requests_df is None:
    st.error("Не вдалося завантажити дані про заявки.")
    st.stop()

# --- БІЧНА ПАНЕЛЬ: ФІЛЬТРИ, ПОШУК, СОРТУВАННЯ ---
st.sidebar.header("Фільтри та пошук")

# Пошук
search_query = st.sidebar.text_input("Пошук (за email, авто):")

# Фільтрація за статусом
status_options = ["Всі"] + sorted(list(requests_df['status'].unique()))
status_filter = st.sidebar.selectbox("Статус:", options=status_options)

# --- ПОКРАЩЕНА ФІЛЬТРАЦІЯ ЦІНИ (DESIRED PRICE) ---
if not requests_df.empty:
    # Визначаємо мінімальну та максимальну ціну з даних
    min_price = int(requests_df['desired_price'].min())
    max_price = int(requests_df['desired_price'].max())

    # Створюємо дві колонки для полів "від" і "до"
    col1, col2 = st.sidebar.columns(2)

    with col1:
        price_from = st.number_input(
            "Бажана ціна від ($)",
            min_value=min_price,
            max_value=max_price,
            value=min_price, # Значення за замовчуванням
            step=500
        )

    with col2:
        price_to = st.number_input(
            "Бажана ціна до ($)",
            min_value=min_price,
            max_value=max_price,
            value=max_price, # Значення за замовчуванням
            step=500
        )
else:
    # Значення за замовчуванням, якщо даних немає
    price_from, price_to = 0, 100000
# ---------------------------------------------------

# Застосування фільтрів
filtered_df = requests_df.copy()

if search_query:
    mask = (
        filtered_df['user_email'].str.contains(search_query, case=False, na=False) |
        filtered_df['car_info'].str.contains(search_query, case=False, na=False)
    )
    filtered_df = filtered_df[mask]

if status_filter != "Всі":
    filtered_df = filtered_df[filtered_df['status'] == status_filter]

# Застосовуємо фільтр ціни
if price_from > price_to:
    st.sidebar.error("Ціна 'від' не може бути більшою за ціну 'до'.")
else:
    if not requests_df.empty:
        filtered_df = filtered_df[
            (filtered_df['desired_price'] >= price_from) & (filtered_df['desired_price'] <= price_to)
        ]
# --- КІНЕЦЬ ОНОВЛЕНОГО БЛОКУ ---

st.dataframe(filtered_df, use_container_width=True)
st.info(f"Знайдено {len(filtered_df)} заявок за вашими критеріями.")

if filtered_df.empty:
    st.stop()

# --- CRUD ОПЕРАЦІЇ ---
st.header("CRUD Операції")
operation = st.selectbox("Оберіть операцію:", ["Створити", "Оновити", "Видалити"])

# === CREATE ===
if operation == "Створити":
    st.subheader("Створити нову заявку на викуп")

    creation_mode = st.radio(
        "Оберіть тип заявки:",
        ("Для НОВОГО автомобіля (ще немає в базі)", "Для ІСНУЮЧОГО автомобіля клієнта")
    )

    # --- Сценарій 1: Новий автомобіль ---
    if creation_mode == "Для НОВОГО автомобіля (ще немає в базі)":
        with st.form("create_request_and_car_form"):
            st.info("Ця форма одночасно створює новий автомобіль в базі та заявку на його викуп.")

            user_id = st.selectbox("Оберіть існуючого клієнта (за email):", options=users_df['user_id'],
                                   key="new_car_user",
                                   format_func=lambda x: users_df.loc[users_df['user_id'] == x, 'email'].iloc[0])
            new_brand_name = st.text_input("Марка")
            new_model_name = st.text_input("Модель")
            vin_code = st.text_input("VIN-код", value=uuid.uuid4().hex[:17].upper())
            year = st.number_input("Рік випуску", min_value=1950, max_value=2025, value=2018)
            mileage = st.number_input("Пробіг", min_value=0, value=120000)
            desired_price = st.number_input("Бажана ціна клієнта:", min_value=0.0, step=500.0)

            submitted = st.form_submit_button("Створити заявку та автомобіль")
            if submitted:
                if not all([new_brand_name, new_model_name, vin_code, desired_price > 0]):
                    st.error("Заповніть всі поля для автомобіля та вкажіть ціну.")
                else:
                    # --- НОВА ПЕРЕВІРКА: Чи немає вже заявки для авто з таким VIN? ---
                    existing_request_vin = run_query(
                        """SELECT br.request_id FROM public."Buyback_Requests" br
                           JOIN public."Cars" c ON br.car_id = c.car_id
                           WHERE c.vin_code = %s AND br.status NOT IN ('completed', 'rejected');""",
                        (vin_code,), fetch="one"
                    )
                    if existing_request_vin:
                        st.error(
                            f"Для автомобіля з VIN-кодом {vin_code} вже існує активна заявка на викуп (ID: {existing_request_vin[0]}).")
                    else:
                        # Якщо все добре, виконуємо транзакцію
                        # ... (тут ваша складна транзакція створення марки, моделі, авто та заявки)
                        st.success("Новий автомобіль та заявка успішно створені!")
                        st.cache_data.clear()
                        st.rerun()

    # --- Сценарій 2: Існуючий автомобіль ---
    elif creation_mode == "Для ІСНУЮЧОГО автомобіля клієнта":
        with st.form("create_request_for_existing_car_form"):
            st.info("Ця форма створює заявку на викуп для автомобіля, який вже є в базі і належить клієнту.")

            user_id = st.selectbox("Клієнт (за email):", options=users_df['user_id'], key="existing_car_user",
                                   format_func=lambda x: users_df.loc[users_df['user_id'] == x, 'email'].iloc[0])

            client_cars_df = run_query(
                "SELECT c.car_id, b.name || ' ' || m.name || ' (' || c.year || ')' AS car_info FROM public.\"Cars\" c "
                "JOIN public.\"Models\" m ON c.model_id = m.model_id "
                "JOIN public.\"Brands\" b ON m.brand_id = b.brand_id "
                "WHERE c.owner_id = %s;", (user_id,), fetch="all")

            if client_cars_df is not None and not client_cars_df.empty:
                car_id = st.selectbox("Автомобіль:", options=client_cars_df['car_id'], format_func=lambda x:
                client_cars_df.loc[client_cars_df['car_id'] == x, 'car_info'].iloc[0])
                desired_price = st.number_input("Бажана ціна клієнта:", min_value=0.0, step=500.0)

                # --- НОВА ПЕРЕВІРКА: Чи немає вже заявки для цього car_id? ---
                existing_request = run_query(
                    "SELECT request_id FROM public.\"Buyback_Requests\" WHERE car_id = %s AND status NOT IN ('completed', 'rejected');",
                    (car_id,), fetch="one"
                )

                submitted = st.form_submit_button("Створити заявку")

                if existing_request:
                    st.error(
                        f"Для обраного автомобіля (ID: {car_id}) вже існує активна заявка на викуп (ID: {existing_request[0]}).")
                elif submitted:
                    run_query(
                        'INSERT INTO public."Buyback_Requests" (user_id, car_id, desired_price) VALUES (%s, %s, %s);',
                        (user_id, car_id, desired_price))
                    st.success("Заявку для існуючого автомобіля успішно створено!")
                    st.cache_data.clear()
                    st.rerun()
            else:
                st.warning("У обраного клієнта немає зареєстрованих автомобілів у базі.")

# === UPDATE ===
elif operation == "Оновити":
    st.subheader("Оновити дані заявки")
    request_to_update_id = st.selectbox("Оберіть ID заявки для оновлення:", options=filtered_df['request_id'])

    if request_to_update_id and employees_df is not None:
        with st.form("update_request_form"):
            manager_id = st.selectbox("Призначити менеджера:", options=employees_df['employee_id'],
                                      format_func=lambda x:
                                      employees_df.loc[employees_df['employee_id'] == x, 'full_name'].iloc[0])
            new_status = st.selectbox("Змінити статус:",
                                      options=['new', 'in_progress', 'inspection_scheduled', 'completed', 'rejected'])
            offer_price = st.number_input("Запропонована ціна (Offer Price):", min_value=0.0, step=500.0)

            if st.form_submit_button("Оновити заявку"):
                run_query(
                    'UPDATE public."Buyback_Requests" SET manager_id = %s, status = %s, offer_price = %s WHERE request_id = %s;',
                    (manager_id, new_status, offer_price, request_to_update_id))
                st.success(f"Заявку ID {request_to_update_id} оновлено!")
                st.cache_data.clear()
                st.rerun()

# === DELETE ===
elif operation == "Видалити":
    st.subheader("Видалити заявку")
    request_to_delete_id = st.selectbox("Оберіть ID заявки для видалення:", options=filtered_df['request_id'])

    if st.button("Видалити"):
        try:
            # Спочатку видаляємо залежні інспекції
            run_query('DELETE FROM public."Inspections" WHERE request_id = %s;', (request_to_delete_id,))
            run_query('DELETE FROM public."Buyback_Requests" WHERE request_id = %s;', (request_to_delete_id,))
            st.success(f"Заявку ID {request_to_delete_id} та пов'язані з нею інспекції видалено!")
            st.cache_data.clear()
            time.sleep(1)
            st.rerun()
        except psycopg2.Error as e:
            st.error(f"Помилка видалення: {e}")

# === ЗАВЕРШЕННЯ ВИКУПУ (Ключова бізнес-логіка) ===
st.header("✅ Завершення викупу автомобіля")
st.warning("Ця дія змінить власника автомобіля на компанію та завершить заявку.")

request_to_complete_id = st.selectbox("Оберіть ID заявки для завершення викупу:",
                                      options=filtered_df[filtered_df['status'] != 'completed']['request_id'])

if st.button("Завершити викуп"):
    if request_to_complete_id:
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # Крок 0: Знаходимо ID системного користувача-компанії
                    cur.execute("SELECT user_id FROM public.\"Users\" WHERE email = 'company@marketplace.com';")
                    company_user_id_tuple = cur.fetchone()
                    if not company_user_id_tuple:
                        st.error(
                            "Системний користувач 'company@marketplace.com' не знайдений в базі. Операцію скасовано.")
                        raise Exception("Company user not found")
                    company_user_id = company_user_id_tuple[0]

                    # Знаходимо car_id з заявки
                    car_id_tuple = run_query("SELECT car_id FROM public.\"Buyback_Requests\" WHERE request_id = %s",
                                             (request_to_complete_id,), fetch="one")
                    if not car_id_tuple:
                        st.error(f"Не вдалося знайти автомобіль для заявки {request_to_complete_id}.")
                        raise Exception("Car not found for request")
                    car_id = car_id_tuple[0]

                    st.info(f"Початок транзакції для заявки {request_to_complete_id}...")

                    # Крок 1: Оновлюємо статус заявки
                    cur.execute('UPDATE public."Buyback_Requests" SET status = %s WHERE request_id = %s;',
                                ('completed', request_to_complete_id))
                    st.info("-> Статус заявки змінено на 'completed'.")

                    # Крок 2: Змінюємо власника автомобіля
                    cur.execute('UPDATE public."Cars" SET owner_id = %s WHERE car_id = %s;', (company_user_id, car_id))
                    st.info(f"-> Власника автомобіля ID {car_id} змінено на компанію (User ID: {company_user_id}).")

                    # Крок 3: Архівуємо всі активні оголошення для цього авто
                    cur.execute('UPDATE public."Sale_Announcements" SET status = %s WHERE car_id = %s AND status = %s;',
                                ('archived', car_id, 'active'))
                    st.info("-> Всі активні оголошення для цього авто архівовано.")

                conn.commit()

            st.success(f"Викуп автомобіля по заявці ID {request_to_complete_id} успішно завершено!")
            st.cache_data.clear()
            time.sleep(2)
            st.rerun()

        except psycopg2.Error as e:
            st.error(f"Помилка бази даних під час транзакції: {e}")
        except Exception as e:
            # Цей блок "зловить" наші власні помилки, як-от "Company user not found"
            pass  # Повідомлення вже було виведено