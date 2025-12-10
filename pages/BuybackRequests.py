import streamlit as st
from db_utils import run_query, log_action, get_db_connection
from navigation import make_sidebar
import pandas as pd
import time

st.set_page_config(page_title="Заявки на викуп", layout="wide")

# --- 🔒 ЗАХИСТ ДОСТУПУ ---
if 'user_id' not in st.session_state or st.session_state['user_id'] is None:
    st.warning("Будь ласка, увійдіть в систему.")
    st.switch_page("main.py")
    st.stop()

if st.session_state['role'] not in ['manager', 'admin']:
    st.error("⛔ Немає доступу! Ця сторінка для Менеджерів.")
    st.stop()

make_sidebar()
# -------------------------------------------

st.title("📥 Управління заявками (Trade-in)")


# --- ЗАВАНТАЖЕННЯ ДАНИХ ---
@st.cache_data
def load_data():
    requests_query = """
    SELECT
        br.request_id, br.status,
        u.email AS user_email,
        b.name AS brand, m.name AS model,
        b.name || ' ' || m.name || ' (' || c.year || ')' AS car_info,
        c.vin_code,
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
    req_df = run_query(requests_query, fetch="all")

    # Довідники
    emps_df = run_query(
        "SELECT employee_id, first_name || ' ' || last_name as full_name FROM public.\"Employees\" WHERE is_active=true;",
        fetch="all")

    return req_df, emps_df


requests_df, employees_df = load_data()

if requests_df is None:
    st.error("Помилка завантаження даних.")
    st.stop()

# --- 🎨 САЙДБАР: ФІЛЬТРИ ---
st.sidebar.header("Фільтри")

# 1. Пошук
search_query = st.sidebar.text_input("🔍 Пошук (Email, VIN):")

# 2. Статус
status_filter = st.sidebar.multiselect("Статус:", options=requests_df['status'].unique())

# 3. Марка та Модель
all_brands = sorted(requests_df['brand'].unique()) if not requests_df.empty else []
brand_filter = st.sidebar.multiselect("Марка:", options=all_brands)

filtered_models = []
if brand_filter:
    filtered_models = sorted(requests_df[requests_df['brand'].isin(brand_filter)]['model'].unique())
else:
    filtered_models = sorted(requests_df['model'].unique()) if not requests_df.empty else []

model_filter = st.sidebar.multiselect("Модель:", options=filtered_models)

# 4. Менеджер
all_managers = sorted(requests_df['manager'].dropna().unique()) if not requests_df.empty else []
manager_filter = st.sidebar.multiselect("Менеджер:", options=all_managers)

# 5. Ціна Клієнта (Desired)
st.sidebar.subheader("Ціна клієнта ($)")
d_c1, d_c2 = st.sidebar.columns(2)
d_min = int(requests_df['desired_price'].min()) if not requests_df.empty else 0
d_max = int(requests_df['desired_price'].max()) if not requests_df.empty else 100000
des_from = d_c1.number_input("Від", value=d_min, step=1000)
des_to = d_c2.number_input("До", value=d_max, step=1000)

# 6. Ціна Компанії (Offer)
st.sidebar.subheader("Наша пропозиція ($)")
o_c1, o_c2 = st.sidebar.columns(2)
o_min = int(requests_df['offer_price'].min()) if not requests_df.empty and requests_df[
    'offer_price'].notna().any() else 0
o_max = int(requests_df['offer_price'].max()) if not requests_df.empty and requests_df[
    'offer_price'].notna().any() else 100000
off_from = o_c1.number_input("Offer Від", value=o_min, step=1000)
off_to = o_c2.number_input("Offer До", value=o_max, step=1000)

# --- ЗАСТОСУВАННЯ ФІЛЬТРІВ ---
filtered_df = requests_df.copy()

if search_query:
    mask = (
            filtered_df['user_email'].str.contains(search_query, case=False, na=False) |
            filtered_df['vin_code'].str.contains(search_query, case=False, na=False)
    )
    filtered_df = filtered_df[mask]

if status_filter:
    filtered_df = filtered_df[filtered_df['status'].isin(status_filter)]

if brand_filter:
    filtered_df = filtered_df[filtered_df['brand'].isin(brand_filter)]

if model_filter:
    filtered_df = filtered_df[filtered_df['model'].isin(model_filter)]

if manager_filter:
    filtered_df = filtered_df[filtered_df['manager'].isin(manager_filter)]

# Фільтр цін
filtered_df = filtered_df[
    (filtered_df['desired_price'] >= des_from) & (filtered_df['desired_price'] <= des_to)
    ]

# Фільтр офера (тільки якщо він є, або показуємо всі якщо 0-0)
# Але логічніше фільтрувати тільки ті, де офер не NULL, якщо користувач змінив дефолтні значення
if off_from > o_min or off_to < o_max:
    filtered_df = filtered_df[
        (filtered_df['offer_price'] >= off_from) & (filtered_df['offer_price'] <= off_to)
        ]

# --- ВІДОБРАЖЕННЯ ---
st.info("👇 Натисніть на рядок у таблиці, щоб обробити заявку.")

display_cols = ['request_id', 'status', 'car_info', 'desired_price', 'offer_price', 'user_email', 'manager']

event = st.dataframe(
    filtered_df[display_cols],
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row"
)

st.caption(f"Знайдено заявок: {len(filtered_df)}")
st.divider()

# --- ОБРОБКА ВИБРАНОЇ ЗАЯВКИ ---
if len(event.selection.rows) > 0:
    selected_index = event.selection.rows[0]
    curr = filtered_df.iloc[selected_index]
    req_id = int(curr['request_id'])

    st.subheader(f"🛠️ Обробка заявки #{req_id}")

    c1, c2 = st.columns([1, 2])

    with c1:
        st.info(f"**Авто:** {curr['car_info']}\n\n**VIN:** `{curr['vin_code']}`")
        st.write(f"**Клієнт:** {curr['user_email']}")
        st.write(f"**Статус:** `{curr['status'].upper()}`")

        # Перевірка інспекції
        insp = run_query('SELECT inspection_id FROM "Inspections" WHERE request_id=%s', (req_id,), fetch="one")
        if insp:
            st.success("✅ Інспекцію проведено")
        else:
            st.warning("⚠️ Інспекцію НЕ проведено")

    with c2:
        # 1. MAKE OFFER
        if curr['status'] in ['new', 'processing', 'inspection_scheduled', 'rejected']:
            st.write("### 💵 Запропонувати ціну")
            with st.form(f"offer_{req_id}"):
                st.write(f"Бажана ціна: **${curr['desired_price']:,.2f}**")

                if curr['status'] == 'rejected':
                    st.error(f"Попередня пропозиція (${curr['offer_price']}) була відхилена.")

                offer_val = float(curr['offer_price']) if curr['offer_price'] else float(curr['desired_price']) * 0.9
                new_offer = st.number_input("Ваша пропозиція ($):", value=offer_val, step=100.0)

                if st.form_submit_button("Надіслати пропозицію"):
                    try:
                        curr_user_id = st.session_state['user_id']
                        emp_res = run_query(
                            """SELECT e.employee_id FROM "Employees" e JOIN "Users" u ON e.email = u.email WHERE u.user_id=%s""",
                            (curr_user_id,), fetch="one")

                        if emp_res:
                            emp_id = emp_res[0]
                            run_query(
                                'UPDATE "Buyback_Requests" SET manager_id=%s, status=\'offer_made\', offer_price=%s WHERE request_id=%s',
                                (emp_id, new_offer, req_id), commit=True)
                            log_action(curr_user_id, "UPDATE", "Buyback_Requests", req_id, f"Offer: ${new_offer}")
                            st.success("Надіслано!");
                            time.sleep(1);
                            st.rerun()
                        else:
                            st.error("Ви не співробітник.")
                    except Exception as e:
                        st.error(f"Помилка: {e}")

        # 2. FINALIZE
        elif curr['status'] == 'approved':
            st.write("### 🤝 Фіналізація")
            if not insp:
                st.error("⛔ Немає інспекції!")
            else:
                st.success("✅ Клієнт погодився. Інспекція є. Можна купувати.")

                # Додаємо унікальний ключ до кнопки, щоб уникнути конфліктів UI
                if st.button("💰 Викупити авто", key=f"fin_btn_{req_id}"):
                    try:
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute("SELECT user_id FROM \"Users\" WHERE email = 'company@marketplace.com'")
                                res = cur.fetchone()
                                # Якщо раптом компанії немає, беремо 1 (але краще створити юзера)
                                comp_id = res[0] if res else 1

                                cur.execute("UPDATE \"Buyback_Requests\" SET status='completed' WHERE request_id=%s",
                                            (req_id,))
                                cur.execute("UPDATE \"Cars\" SET owner_id=%s WHERE car_id=%s",
                                            (comp_id, int(curr['car_id'])))
                                cur.execute("UPDATE \"Sale_Announcements\" SET status='archived' WHERE car_id=%s",
                                            (int(curr['car_id']),))
                            conn.commit()

                        log_action(st.session_state['user_id'], "TRANSACTION", "Buyback", req_id, "Completed")

                        # --- ВАЖЛИВО: ОЧИЩАЄМО КЕШ ТУТ ---
                        st.cache_data.clear()
                        # ---------------------------------

                        st.balloons()
                        st.success("Успішно! Авто перейшло у власність компанії.")
                        time.sleep(2)
                        st.rerun()

                    except Exception as e:
                        st.error(f"Помилка: {e}")

        # 3. WAIT
        elif curr['status'] == 'offer_made':
            st.info(f"⏳ Чекаємо відповіді клієнта (Офер: ${curr['offer_price']})")

        # DELETE
        if curr['status'] != 'completed':
            st.write("---")
            if st.button("🗑️ Видалити заявку", key=f"del_{req_id}"):
                run_query('DELETE FROM "Buyback_Requests" WHERE request_id=%s', (req_id,), commit=True)
                log_action(st.session_state['user_id'], "DELETE", "Buyback_Requests", req_id, "Deleted")
                st.success("Видалено.");
                st.cache_data.clear();
                time.sleep(1);
                st.rerun()

else:
    st.info("👈 Оберіть заявку.")