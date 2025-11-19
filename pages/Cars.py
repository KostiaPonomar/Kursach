import psycopg2
import streamlit as st
from db_utils import run_query, get_db_connection
import uuid
import pandas as pd
import time

st.set_page_config(page_title="Автомобілі", layout="wide")
st.title("🚗 Автомобілі")


# --- ФУНКЦІЇ ДЛЯ ЗАВАНТАЖЕННЯ ДАНИХ ---
@st.cache_data
def load_all_data():
    """Завантажує всі необхідні дані для сторінки одним махом."""
    cars = run_query(
        """SELECT 
            c.car_id, b.name AS brand, m.name AS model, u.email AS owner_email,
            c.vin_code, c.year, c.mileage
           FROM public."Cars" c
           LEFT JOIN public."Models" m ON c.model_id = m.model_id
           LEFT JOIN public."Brands" b ON m.brand_id = b.brand_id
           LEFT JOIN public."Users" u ON c.owner_id = u.user_id
           ORDER BY c.car_id;""", fetch="all"
    )
    users = run_query('SELECT user_id, email FROM public."Users" ORDER BY email;', fetch="all")
    characteristics = run_query('SELECT characteristic_id, name FROM public."Characteristics";', fetch="all")
    return cars, users, characteristics


cars_df, users_df, characteristics_df = load_all_data()

if cars_df is None:
    st.error("Не вдалося завантажити дані про автомобілі. Перевірте підключення до БД.")
    st.stop()

# --- БІЧНА ПАНЕЛЬ: ФІЛЬТРИ ТА СОРТУВАННЯ ---
st.sidebar.header("Фільтри та сортування")
brand_options = ["Всі"] + sorted(list(cars_df['brand'].unique()))
brand_filter = st.sidebar.selectbox("Марка:", options=brand_options)
search_vin = st.sidebar.text_input("Пошук за VIN-кодом:")
sort_column = st.sidebar.selectbox("Сортувати за:", options=cars_df.columns)
sort_ascending = st.sidebar.toggle("За зростанням", value=True)

filtered_df = cars_df.copy()
if brand_filter != "Всі": filtered_df = filtered_df[filtered_df['brand'] == brand_filter]
if search_vin: filtered_df = filtered_df[filtered_df['vin_code'].str.contains(search_vin, case=False)]
if not filtered_df.empty: filtered_df.sort_values(by=sort_column, ascending=sort_ascending, inplace=True)

st.dataframe(filtered_df, use_container_width=True)

# --- УПРАВЛІННЯ ХАРАКТЕРИСТИКАМИ ---
st.header("Управління характеристиками автомобіля")
if not filtered_df.empty:
    selected_car_id_char = st.selectbox("Оберіть ID авто для роботи з характеристиками:", options=filtered_df['car_id'])

    current_chars_df = run_query(
        "SELECT characteristic_id, value FROM public.\"Car_Characteristics\" WHERE car_id = %s;",
        (selected_car_id_char,), fetch="all")
    current_chars_dict = dict(
        zip(current_chars_df['characteristic_id'], current_chars_df['value'])) if current_chars_df is not None else {}

    with st.form("characteristics_form"):
        new_char_values = {}
        for _, char_row in characteristics_df.iterrows():
            char_id, char_name = char_row['characteristic_id'], char_row['name']
            current_value = current_chars_dict.get(char_id, "")
            new_char_values[char_id] = st.text_input(f"{char_name}:", value=current_value)

        if st.form_submit_button("Зберегти характеристики"):
            try:
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        for char_id, new_value in new_char_values.items():
                            if new_value:
                                cur.execute("""INSERT INTO public."Car_Characteristics" (car_id, characteristic_id, value) VALUES (%s, %s, %s)
                                               ON CONFLICT (car_id, characteristic_id) DO UPDATE SET value = EXCLUDED.value;""",
                                            (selected_car_id_char, char_id, new_value))
                            elif char_id in current_chars_dict:
                                cur.execute(
                                    'DELETE FROM public."Car_Characteristics" WHERE car_id = %s AND characteristic_id = %s;',
                                    (selected_car_id_char, char_id))
                    conn.commit()
                st.success("Характеристики успішно оновлено!")
            except psycopg2.Error as e:
                st.error(f"Помилка бази даних: {e}")

# --- CRUD ОПЕРАЦІЇ ---
st.header("CRUD Операції")
operation = st.selectbox("Оберіть операцію:", ["Створити (Create)", "Оновити (Update)", "Видалити (Delete)"])

# === CREATE ===
if operation == "Створити (Create)":
    st.subheader("Додати новий автомобіль")
    if users_df is not None:
        with st.form("create_car_form"):
            st.write("Заповніть дані. Якщо марки/моделі немає в базі, вони будуть створені.")
            new_brand_name = st.text_input("Марка (напр., 'Tesla')")
            new_model_name = st.text_input("Модель (напр., 'Model Y')")
            owner_id = st.selectbox("Власник (за email):", options=users_df['user_id'],
                                    format_func=lambda x: users_df.loc[users_df['user_id'] == x, 'email'].iloc[0])
            vin_code = st.text_input("VIN-код", value=uuid.uuid4().hex[:17].upper())
            year = st.number_input("Рік випуску", min_value=1950, max_value=2025, value=2020)
            mileage = st.number_input("Пробіг", min_value=0, value=50000)

            if st.form_submit_button("Додати автомобіль"):
                if not all([new_brand_name, new_model_name, vin_code]):
                    st.error("Будь ласка, заповніть поля 'Марка', 'Модель' та 'VIN-код'.")
                else:
                    try:
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                # Крок 1: Знайти або створити Марку
                                cur.execute('SELECT brand_id FROM public."Brands" WHERE name = %s;', (new_brand_name,))
                                brand_id_tuple = cur.fetchone()
                                if brand_id_tuple:
                                    brand_id = brand_id_tuple[0]
                                else:
                                    cur.execute('INSERT INTO public."Brands" (name) VALUES (%s) RETURNING brand_id;',
                                                (new_brand_name,))
                                    brand_id = cur.fetchone()[0]

                                # Крок 2: Знайти або створити Модель
                                cur.execute('SELECT model_id FROM public."Models" WHERE name = %s AND brand_id = %s;',
                                            (new_model_name, brand_id))
                                model_id_tuple = cur.fetchone()
                                if model_id_tuple:
                                    model_id = model_id_tuple[0]
                                else:
                                    cur.execute(
                                        'INSERT INTO public."Models" (brand_id, name) VALUES (%s, %s) RETURNING model_id;',
                                        (brand_id, new_model_name))
                                    model_id = cur.fetchone()[0]

                                # Крок 3: Створити Автомобіль
                                cur.execute(
                                    """INSERT INTO public."Cars" (model_id, owner_id, vin_code, year, mileage) VALUES (%s, %s, %s, %s, %s);""",
                                    (model_id, owner_id, vin_code, year, mileage))
                            conn.commit()
                        st.success(f"Автомобіль {new_brand_name} {new_model_name} успішно додано!")
                        st.cache_data.clear()
                        time.sleep(1)
                        st.rerun()
                    except psycopg2.Error as e:
                        st.error(f"Помилка бази даних при додаванні: {e}")
    else:
        st.error("Не вдалося завантажити дані для користувачів.")


# === UPDATE ===
elif operation == "Оновити (Update)":
    st.subheader("Оновити дані автомобіля")
    if not filtered_df.empty:
        car_to_update = st.selectbox("Оберіть ID авто для оновлення:", options=filtered_df['car_id'], key="upd_car")
        current_mileage = filtered_df[filtered_df['car_id'] == car_to_update]['mileage'].iloc[0]
        new_mileage = st.number_input("Новий пробіг:", value=current_mileage)
        if st.button("Оновити пробіг"):
            run_query('UPDATE public."Cars" SET mileage = %s WHERE car_id = %s;', (new_mileage, car_to_update))
            st.success(f"Пробіг для авто ID {car_to_update} оновлено!")
            st.session_state.cars_df = load_all_data()
            st.rerun()

# === DELETE ===
elif operation == "Видалити (Delete)":
    st.subheader("Видалити автомобіль")
    if not filtered_df.empty:
        if 'car_to_delete' not in st.session_state:
            st.session_state.car_to_delete = filtered_df['car_id'].iloc[0]

        st.selectbox("Оберіть ID авто для видалення:", options=filtered_df['car_id'], key="car_to_delete")

        if st.button("Видалити авто"):
            car_id = st.session_state.car_to_delete
            success = True
            try:
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute('SELECT announcement_id FROM public."Sale_Announcements" WHERE car_id = %s;',
                                    (car_id,))
                        announcement_ids = [item[0] for item in cur.fetchall()]
                        if announcement_ids:
                            cur.execute('DELETE FROM public."Deals" WHERE announcement_id IN %s;',
                                        (tuple(announcement_ids),))
                            cur.execute('DELETE FROM public."Sale_Announcements" WHERE car_id = %s;', (car_id,))

                        cur.execute(
                            """DELETE FROM public."Inspections" WHERE request_id IN (SELECT request_id FROM public."Buyback_Requests" WHERE car_id = %s);""",
                            (car_id,))
                        cur.execute('DELETE FROM public."Buyback_Requests" WHERE car_id = %s;', (car_id,))
                        cur.execute('DELETE FROM public."Cars" WHERE car_id = %s;', (car_id,))
                    conn.commit()
            except psycopg2.Error as e:
                st.error(f"Помилка під час видалення: {e}")
                success = False

            if success:
                st.success(f"Авто ID {car_id} та всі пов'язані з ним дані успішно видалено!")
                st.session_state.cars_df = load_all_data()
                import time

                time.sleep(2)
                st.rerun()

# --- СТВОРЕННЯ ОГОЛОШЕННЯ (залишаємо цю корисну функцію) ---
st.header("Створити оголошення для автомобіля")
if not filtered_df.empty:
    car_for_announcement = st.selectbox(
        "Оберіть ID авто для створення оголошення:",
        options=filtered_df['car_id'],
        key="create_ann_car"
    )

    # 1. ПЕРЕВІРКА: Чи не знаходиться авто у процесі викупу?
    active_buyback_query = """
    SELECT request_id, status FROM public."Buyback_Requests"
    WHERE car_id = %s AND status NOT IN ('completed', 'rejected');
    """
    active_buyback = run_query(active_buyback_query, (car_for_announcement,), fetch="one")

    # 2. ВИЗНАЧЕННЯ ВЛАСНИКА
    owner_query = "SELECT u.user_id, u.email FROM public.\"Cars\" c JOIN public.\"Users\" u ON c.owner_id = u.user_id WHERE c.car_id = %s;"
    owner_data = run_query(owner_query, (car_for_announcement,), fetch="one")

    if not owner_data:
        st.error("Власника авто не знайдено!")
        st.stop()

    owner_id, owner_email = owner_data

    if active_buyback:
        st.error(
            f"Неможливо створити оголошення: авто ID {car_for_announcement} у процесі викупу (Статус: '{active_buyback[1]}').")

    else:
        # Визначаємо попередні дані (якщо оголошення вже було, підтягнемо ціну і опис)
        prev_ad = run_query(
            'SELECT title, description, price, status FROM public."Sale_Announcements" WHERE car_id = %s',
            (car_for_announcement,), fetch="one")

        # Логіка заголовка форми
        if owner_email == 'company@marketplace.com':
            st.info("Авто належить компанії. Продаж від імені компанії.")
            is_company = True
        else:
            is_company = False

        # Якщо оголошення вже активне - попередження
        if prev_ad and prev_ad[3] == 'active':
            st.warning(f"Увага! Для цього авто вже є АКТИВНЕ оголошення. Створення нового перезапише старе.")

        with st.form("create_ann_form"):
            car_row = filtered_df[filtered_df['car_id'] == car_for_announcement].iloc[0]

            # Значення за замовчуванням (з попереднього оголошення або згенеровані)
            def_title = prev_ad[0] if prev_ad else f"{car_row['brand']} {car_row['model']} {car_row['year']} року"
            def_desc = prev_ad[1] if prev_ad else "Опис автомобіля..."
            def_price = float(prev_ad[2]) if prev_ad else 10000.0

            title = st.text_input("Заголовок оголошення", value=def_title)
            price = st.number_input("Ціна (USD)", min_value=0.0, step=100.0, value=def_price)
            description = st.text_area("Опис", value=def_desc)

            submit_btn = st.form_submit_button("Опублікувати / Оновити оголошення")

            if submit_btn:
                try:
                    # ВИПРАВЛЕННЯ: Використовуємо INSERT ... ON CONFLICT
                    upsert_query = """
                    INSERT INTO public."Sale_Announcements" 
                    (car_id, seller_user_id, title, description, price, status, creation_date) 
                    VALUES (%s, %s, %s, %s, %s, 'active', CURRENT_TIMESTAMP)
                    ON CONFLICT (car_id) 
                    DO UPDATE SET 
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        price = EXCLUDED.price,
                        status = 'active',
                        seller_user_id = EXCLUDED.seller_user_id,
                        creation_date = CURRENT_TIMESTAMP;
                    """
                    # seller_user_id беремо реального власника (компанія або людина)
                    run_query(upsert_query, (car_for_announcement, owner_id, title, description, price))

                    st.success(f"Оголошення для авто ID {car_for_announcement} успішно збережено!")
                    time.sleep(1.5)
                    st.rerun()

                except psycopg2.Error as e:
                    st.error(f"Помилка бази даних: {e}")