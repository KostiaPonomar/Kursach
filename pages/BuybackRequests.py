import uuid
import streamlit as st
from db_utils import run_query, get_db_connection
import pandas as pd
import psycopg2
import time

st.set_page_config(page_title="Заявки на викуп", layout="wide")
st.title("📥 Заявки на викуп (Trade-in)")


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
    users = run_query('SELECT user_id, email FROM public."Users" ORDER BY email;', fetch="all")
    employees = run_query("SELECT employee_id, first_name || ' ' || last_name as full_name FROM public.\"Employees\";",
                          fetch="all")

    return requests, users, employees


requests_df, users_df, employees_df = load_all_buyback_data()

if requests_df is None:
    st.error("Не вдалося завантажити дані про заявки.")
    st.stop()

# --- БІЧНА ПАНЕЛЬ ---
st.sidebar.header("Фільтри")
search_query = st.sidebar.text_input("Пошук (email, авто):")
status_options = ["Всі"] + sorted(list(requests_df['status'].unique()))
status_filter = st.sidebar.selectbox("Статус:", options=status_options)

# Фільтрація
filtered_df = requests_df.copy()
if search_query:
    mask = (filtered_df['user_email'].str.contains(search_query, case=False, na=False) |
            filtered_df['car_info'].str.contains(search_query, case=False, na=False))
    filtered_df = filtered_df[mask]
if status_filter != "Всі":
    filtered_df = filtered_df[filtered_df['status'] == status_filter]

st.dataframe(filtered_df, use_container_width=True)

# --- CRUD ОПЕРАЦІЇ ---
st.header("Управління заявками")
operation = st.selectbox("Оберіть дію:", ["Створити заявку", "Оновити статус/менеджера", "Видалити заявку"])

# ==========================================
# === CREATE (СТВОРЕННЯ) ===
# ==========================================
if operation == "Створити заявку":
    st.subheader("Нова заявка")
    creation_mode = st.radio("Тип заявки:", ("Для існуючого авто клієнта", "Для НОВОГО авто (немає в базі)"))

    # --- СЦЕНАРІЙ 1: ІСНУЮЧЕ АВТО ---
    if creation_mode == "Для існуючого авто клієнта":
        st.write("Крок 1: Оберіть клієнта")

        # 1. ВИНОСИМО ВИБІР КЛІЄНТА ЗА МЕЖІ ФОРМИ
        # Тепер при зміні клієнта сторінка оновиться і завантажить його машини
        user_id = st.selectbox(
            "Клієнт:",
            options=users_df['user_id'],
            format_func=lambda x: users_df.loc[users_df['user_id'] == x, 'email'].iloc[0],
            key="select_user_dynamic"  # Унікальний ключ
        )

        # 2. РОБИМО ЗАПИТ АВТОМОБІЛІВ (одразу після вибору юзера)
        client_cars = run_query(
            """SELECT c.car_id, b.name || ' ' || m.name || ' (' || c.year || ')' AS info 
               FROM public."Cars" c 
               JOIN public."Models" m ON c.model_id = m.model_id 
               JOIN public."Brands" b ON m.brand_id = b.brand_id 
               WHERE c.owner_id = %s""", (user_id,), fetch="all")

        # 3. ВІДОБРАЖАЄМО ФОРМУ (Тільки для вибору авто і ціни)
        if client_cars is not None and not client_cars.empty:
            with st.form("exist_car_form"):
                st.write("Крок 2: Оберіть авто та ціну")

                car_id = st.selectbox(
                    "Автомобіль:",
                    options=client_cars['car_id'],
                    format_func=lambda x: client_cars.loc[client_cars['car_id'] == x, 'info'].iloc[0]
                )

                desired_price = st.number_input("Бажана ціна ($):", min_value=0.0, step=100.0)

                if st.form_submit_button("Створити заявку"):
                    # Перевірка дублікатів
                    exists = run_query(
                        'SELECT request_id FROM public."Buyback_Requests" WHERE car_id=%s AND status NOT IN (\'completed\', \'rejected\')',
                        (car_id,), fetch="one")

                    if exists:
                        st.error(f"Заявка вже існує (ID {exists[0]})!")
                    else:
                        run_query(
                            'INSERT INTO public."Buyback_Requests" (user_id, car_id, desired_price, status) VALUES (%s, %s, %s, \'new\')',
                            (user_id, car_id, desired_price))
                        st.success("Заявку створено!")
                        st.cache_data.clear()
                        time.sleep(1)
                        st.rerun()
        else:
            st.warning("У цього клієнта немає авто в гаражі.")

    # --- СЦЕНАРІЙ 2: НОВЕ АВТО (СКЛАДНА ТРАНЗАКЦІЯ) ---
    else:
        with st.form("new_car_form"):
            st.info("Створення авто та заявки однією дією.")
            user_id = st.selectbox("Клієнт:", options=users_df['user_id'],
                                   format_func=lambda x: users_df.loc[users_df['user_id'] == x, 'email'].iloc[0])

            c1, c2 = st.columns(2)
            brand_name = c1.text_input("Марка (Brand)")
            model_name = c2.text_input("Модель")
            vin = st.text_input("VIN", value=uuid.uuid4().hex[:17].upper())
            year = st.number_input("Рік", 1980, 2025, 2020)
            mileage = st.number_input("Пробіг", 0, 500000, 50000)
            price = st.number_input("Бажана ціна ($)", min_value=0.0)

            if st.form_submit_button("Створити все"):
                if not all([brand_name, model_name, vin]):
                    st.error("Заповніть Марку, Модель та VIN!")
                else:
                    try:
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                # 1. Знайти або створити Brand
                                cur.execute('SELECT brand_id FROM public."Brands" WHERE name = %s', (brand_name,))
                                res = cur.fetchone()
                                if res:
                                    b_id = res[0]
                                else:
                                    cur.execute('INSERT INTO public."Brands" (name) VALUES (%s) RETURNING brand_id',
                                                (brand_name,))
                                    b_id = cur.fetchone()[0]

                                # 2. Знайти або створити Model
                                cur.execute('SELECT model_id FROM public."Models" WHERE name = %s AND brand_id = %s',
                                            (model_name, b_id))
                                res = cur.fetchone()
                                if res:
                                    m_id = res[0]
                                else:
                                    cur.execute(
                                        'INSERT INTO public."Models" (brand_id, name) VALUES (%s, %s) RETURNING model_id',
                                        (b_id, model_name))
                                    m_id = cur.fetchone()[0]

                                # 3. Створити Car
                                cur.execute("""
                                    INSERT INTO public."Cars" (model_id, owner_id, vin_code, year, mileage) 
                                    VALUES (%s, %s, %s, %s, %s) RETURNING car_id
                                """, (m_id, user_id, vin, year, mileage))
                                new_car_id = cur.fetchone()[0]

                                # 4. Створити Request
                                cur.execute("""
                                    INSERT INTO public."Buyback_Requests" (car_id, user_id, desired_price, status) 
                                    VALUES (%s, %s, %s, 'new')
                                """, (new_car_id, user_id, price))

                            conn.commit()  # Зберігаємо все разом
                        st.success("Авто та заявку успішно додано!")
                        st.cache_data.clear()
                        time.sleep(1)
                        st.rerun()
                    except psycopg2.Error as e:
                        st.error(f"Помилка БД: {e}")

# ==========================================
# === UPDATE (ОНОВЛЕННЯ) ===
# ==========================================
elif operation == "Оновити статус/менеджера":
    st.subheader("Робота з заявкою")
    req_id = st.selectbox("ID Заявки:", options=filtered_df['request_id'])

    if req_id:
        curr_row = filtered_df[filtered_df['request_id'] == req_id].iloc[0]

        with st.form("upd_req"):
            # Статуси мають відповідати ENUM в БД!
            status_enum = ['new', 'processing', 'inspection_scheduled', 'offer_made', 'approved', 'rejected',
                           'completed']

            # Вибір менеджера
            cur_mgr_idx = 0  # Логіка для визначення індексу, якщо менеджер вже є, пропущена для спрощення
            mgr_id = st.selectbox("Менеджер:", options=employees_df['employee_id'],
                                  format_func=lambda x:
                                  employees_df.loc[employees_df['employee_id'] == x, 'full_name'].iloc[0])

            # Вибір статусу
            try:
                st_idx = status_enum.index(curr_row['status'])
            except:
                st_idx = 0
            new_status = st.selectbox("Статус:", options=status_enum, index=st_idx)

            offer = st.number_input("Запропонована ціна ($):",
                                    value=float(curr_row['offer_price'] if curr_row['offer_price'] else 0.0))

            if st.form_submit_button("Зберегти зміни"):
                run_query(
                    'UPDATE public."Buyback_Requests" SET manager_id=%s, status=%s, offer_price=%s WHERE request_id=%s',
                    (mgr_id, new_status, offer, req_id))
                st.success("Оновлено!")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()

# ==========================================
# === DELETE (ВИДАЛЕННЯ) ===
# ==========================================
elif operation == "Видалити заявку":
    req_id = st.selectbox("ID Заявки для видалення:", options=filtered_df['request_id'])
    if st.button("🗑️ Видалити назавжди"):
        run_query('DELETE FROM public."Buyback_Requests" WHERE request_id=%s', (req_id,))
        st.success("Видалено.")
        st.cache_data.clear()
        time.sleep(1)
        st.rerun()

# ==========================================
# === ФІНАЛІЗАЦІЯ (ОКРЕМИЙ БЛОК) ===
# ==========================================
st.divider()
st.header("🤝 Фіналізація (Купівля авто компанією)")

# Показуємо тільки ті, що погоджені клієнтом (approved) або де вже зроблена пропозиція
# Але можна залишити і всі не завершені
candidates = filtered_df[~filtered_df['status'].isin(['completed', 'rejected'])]

if not candidates.empty:
    fin_req_id = st.selectbox("Оберіть заявку для закриття угоди:", options=candidates['request_id'])

    # Перевірка наявності інспекції (Бізнес-правило!)
    insp = run_query('SELECT inspection_id FROM public."Inspections" WHERE request_id=%s', (fin_req_id,), fetch="one")

    if not insp:
        st.warning("⚠️ Увага: Для цієї заявки ще не проведено технічну інспекцію! Викуп не рекомендований.")
    else:
        st.success("✅ Технічна інспекція проведена.")

    if st.button("✅ Завершити викуп (Переписати авто на Компанію)"):
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # 1. Отримуємо ID компанії
                    cur.execute("SELECT user_id FROM public.\"Users\" WHERE email = 'company@marketplace.com'")
                    res = cur.fetchone()
                    if not res: raise Exception("Створіть юзера company@marketplace.com!")
                    comp_id = res[0]

                    # 2. Отримуємо ID авто
                    cur.execute('SELECT car_id FROM public."Buyback_Requests" WHERE request_id=%s', (fin_req_id,))
                    car_id = cur.fetchone()[0]

                    # 3. Транзакція завершення
                    cur.execute('UPDATE public."Buyback_Requests" SET status=\'completed\' WHERE request_id=%s',
                                (fin_req_id,))
                    cur.execute('UPDATE public."Cars" SET owner_id=%s WHERE car_id=%s', (comp_id, car_id))
                    # Архівуємо старі оголошення
                    cur.execute("UPDATE public.\"Sale_Announcements\" SET status='archived' WHERE car_id=%s", (car_id,))

                conn.commit()
            st.balloons()
            st.success(f"Угода {fin_req_id} закрита! Автомобіль перейшов у власність компанії.")
            st.cache_data.clear()
            time.sleep(2)
            st.rerun()
        except Exception as e:
            st.error(f"Помилка: {e}")
else:
    st.info("Немає активних заявок для завершення.")