import streamlit as st
from db_utils import run_query, log_action, get_db_connection
from auth import make_hash  # <--- ПОТРІБНО ДЛЯ ПАРОЛІВ
from navigation import make_sidebar
import pandas as pd
import psycopg2
from faker import Faker
import time

st.set_page_config(page_title="Співробітники", layout="wide")

# --- 🔒 ЗАХИСТ ДОСТУПУ (Тільки Адмін) ---
if 'user_id' not in st.session_state or st.session_state['user_id'] is None:
    st.warning("Будь ласка, увійдіть в систему.")
    st.switch_page("main.py")
    st.stop()

if st.session_state['role'] != 'admin':
    st.error("⛔ Немає доступу! Ця сторінка тільки для Адміністраторів.")
    st.stop()

make_sidebar()
# ---------------------------------------

st.title("🧑‍💼 Управління персоналом")


# --- ЗАВАНТАЖЕННЯ ДАНИХ ---
@st.cache_data
def load_data():
    # Об'єднуємо Employees та Users, щоб бачити роль і телефон
    employees_query = """
    SELECT
        e.employee_id, 
        e.first_name, 
        e.last_name, 
        p.name AS position,
        e.email, 
        u.phone_number,
        u.role,
        e.is_active
    FROM public."Employees" e
    JOIN public."Positions" p ON e.position_id = p.position_id
    LEFT JOIN public."Users" u ON e.email = u.email -- Зв'язок по Email
    ORDER BY e.employee_id;
    """
    emp_df = run_query(employees_query, fetch="all")

    pos_query = 'SELECT position_id, name FROM public."Positions";'
    pos_df = run_query(pos_query, fetch="all")

    return emp_df, pos_df


employees_df, positions_df = load_data()

if employees_df is None:
    st.error("Помилка завантаження даних.")
    st.stop()

# --- 🎨 САЙДБАР: ФІЛЬТРИ ---
st.sidebar.header("Фільтри та пошук")

search_query = st.sidebar.text_input("🔍 Пошук (Ім'я / Email):")
role_filter = st.sidebar.multiselect("Посада:", options=employees_df['position'].unique())
status_filter = st.sidebar.radio("Статус:", ["Всі", "Активні", "Звільнені"])

filtered_df = employees_df.copy()

if search_query:
    mask = (
            filtered_df['first_name'].str.contains(search_query, case=False) |
            filtered_df['last_name'].str.contains(search_query, case=False) |
            filtered_df['email'].str.contains(search_query, case=False)
    )
    filtered_df = filtered_df[mask]

if role_filter:
    filtered_df = filtered_df[filtered_df['position'].isin(role_filter)]

if status_filter == "Активні":
    filtered_df = filtered_df[filtered_df['is_active'] == True]
elif status_filter == "Звільнені":
    filtered_df = filtered_df[filtered_df['is_active'] == False]

# --- ВІДОБРАЖЕННЯ ---
st.dataframe(filtered_df, use_container_width=True)
st.info(f"Знайдено співробітників: {len(filtered_df)}")

st.divider()

# --- CRUD ОПЕРАЦІЇ ---
st.subheader("🛠️ Управління акаунтами")
operation = st.selectbox("Оберіть дію:", ["Створити акаунт менеджера", "Редагувати дані", "Деактивувати (Звільнити)"])

# ==========================================
# === CREATE (USERS + EMPLOYEES) ===
# ==========================================
if operation == "Створити акаунт менеджера":
    st.markdown("Ця форма створить **користувача для входу** та **картку співробітника** одночасно.")


    defaults = st.session_state.get('new_emp', {})

    with st.form("create_employee"):
        c1, c2 = st.columns(2)
        first_name = c1.text_input("Ім'я", value=defaults.get('first', ''))
        last_name = c2.text_input("Прізвище", value=defaults.get('last', ''))

        c3, c4 = st.columns(2)
        email = c3.text_input("Email", value=defaults.get('email', ''))
        phone = c4.text_input("Телефон", value=defaults.get('phone', ''))

        c5, c6 = st.columns(2)
        password = c5.text_input("Пароль", type="password")
        role_select = c6.selectbox("Роль доступу:", ["manager", "admin"])

        position_id = st.selectbox(
            "Посада (для відображення):",
            options=positions_df['position_id'],
            format_func=lambda x: positions_df.loc[positions_df['position_id'] == x, 'name'].iloc[0]
        )

        if st.form_submit_button("Створити співробітника"):
            if not all([first_name, last_name, email, password]):
                st.error("Заповніть всі поля!")
            else:
                try:
                    hashed_pass = make_hash(password)

                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            # 1. Створюємо (або оновлюємо) User
                            cur.execute("""
                                INSERT INTO public."Users" (first_name, last_name, email, phone_number, password_hash, role)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT (email) DO UPDATE SET 
                                    role = EXCLUDED.role, password_hash = EXCLUDED.password_hash
                                RETURNING user_id;
                            """, (first_name, last_name, email, phone, hashed_pass, role_select))
                            user_id = cur.fetchone()[0]

                            # 2. Створюємо Employee
                            cur.execute("""
                                INSERT INTO public."Employees" (first_name, last_name, position_id, email, is_active) 
                                VALUES (%s, %s, %s, %s, true)
                                RETURNING employee_id;
                            """, (first_name, last_name, position_id, email))
                            emp_id = cur.fetchone()[0]

                        conn.commit()

                    log_action(st.session_state['user_id'], "INSERT", "Users/Employees", emp_id,
                               f"Створено менеджера {email}")
                    st.success(f"Акаунт створено! ID: {emp_id}. Можна входити.")

                    if 'new_emp' in st.session_state: del st.session_state['new_emp']
                    st.cache_data.clear()
                    time.sleep(2)
                    st.rerun()

                except Exception as e:
                    st.error(f"Помилка (можливо такий email вже є): {e}")

# ==========================================
# === UPDATE ===
# ==========================================
elif operation == "Редагувати дані":
    emp_id = st.selectbox("Оберіть співробітника:", options=filtered_df['employee_id'])

    if emp_id:
        curr = employees_df[employees_df['employee_id'] == emp_id].iloc[0]

        with st.form("update_employee"):
            new_email = st.text_input("Email (Зміна Email змінить логін!)", value=curr['email'])
            new_phone = st.text_input("Телефон", value=curr['phone_number'] if curr['phone_number'] else "")

            # Знаходимо поточний індекс посади
            pos_idx = 0
            current_pos_rows = positions_df[positions_df['name'] == curr['position']]
            if not current_pos_rows.empty:
                pos_idx = list(positions_df['position_id']).index(current_pos_rows.iloc[0]['position_id'])

            new_pos = st.selectbox("Посада:", options=positions_df['position_id'], index=pos_idx,
                                   format_func=lambda x:
                                   positions_df.loc[positions_df['position_id'] == x, 'name'].iloc[0])

            new_role = st.selectbox("Роль доступу:", ["manager", "admin", "client"],
                                    index=["manager", "admin", "client"].index(curr['role']) if curr['role'] else 0)

            if st.form_submit_button("Зберегти зміни"):
                try:
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            # Оновлюємо Employees
                            cur.execute("""
                                UPDATE public."Employees" SET email=%s, position_id=%s 
                                WHERE employee_id=%s
                            """, (new_email, new_pos, emp_id))

                            # Оновлюємо Users (синхронізація)
                            cur.execute("""
                                UPDATE public."Users" SET email=%s, phone_number=%s, role=%s 
                                WHERE email=%s
                            """, (new_email, new_phone, new_role,
                                  curr['email']))  # Використовуємо старий email для пошуку юзера

                        conn.commit()

                    log_action(st.session_state['user_id'], "UPDATE", "Employees", int(emp_id),
                               f"Оновлено дані для {new_email}")
                    st.success("Дані оновлено!")
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Помилка: {e}")

# ==========================================
# === DELETE (DEACTIVATE) ===
# ==========================================
elif operation == "Деактивувати (Звільнити)":
    emp_id = st.selectbox("Оберіть співробітника:", options=filtered_df['employee_id'])

    st.warning("Це забере доступ до системи, але збереже історію дій.")

    if st.button("🚫 Заблокувати доступ"):
        try:
            curr_email = employees_df[employees_df['employee_id'] == emp_id].iloc[0]['email']

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # 1. Ставимо is_active = False в Employees
                    cur.execute('UPDATE "Employees" SET is_active=false WHERE employee_id=%s', (emp_id,))
                    # 2. Змінюємо роль на 'client' в Users (щоб не міг зайти в адмінку)
                    cur.execute('UPDATE "Users" SET role=\'client\' WHERE email=%s', (curr_email,))

                conn.commit()

            log_action(st.session_state['user_id'], "DEACTIVATE", "Employees", int(emp_id), "Звільнення співробітника")
            st.success("Співробітника деактивовано.")
            st.cache_data.clear()
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"Помилка: {e}")