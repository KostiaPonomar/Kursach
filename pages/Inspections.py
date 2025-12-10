import streamlit as st
from db_utils import run_query, log_action, get_db_connection
import pandas as pd
import datetime
import time
from navigation import make_sidebar

st.set_page_config(page_title="Технічні інспекції", layout="wide")

# --- 🔒 ЗАХИСТ ДОСТУПУ ---
if 'user_id' not in st.session_state or st.session_state['user_id'] is None:
    st.warning("Будь ласка, увійдіть в систему.")
    st.switch_page("main.py")
    st.stop()

if st.session_state['role'] not in ['manager', 'admin']:
    st.error("⛔ Немає доступу! Ця сторінка для Менеджерів.")
    st.stop()

make_sidebar()
# ---------------------------

st.title("🔧 Технічні інспекції")

STANDARD_CHECKPOINTS = ["Двигун", "Коробка передач", "Ходова частина", "Кузов та ЛФП", "Салон", "Електроніка"]


@st.cache_data
def load_data():
    # 1. Історія інспекцій (ОНОВЛЕНО: Додано AVG рейтинг та окремі колонки бренду/моделі)
    history_query = """
    SELECT 
        i.inspection_id,
        br.request_id,
        b.name AS brand,
        m.name AS model,
        b.name || ' ' || m.name || ' (' || c.vin_code || ')' AS car_info,
        c.vin_code,
        e.first_name || ' ' || e.last_name AS inspector_name,
        i.inspection_date,
        i.final_conclusion,
        ROUND(AVG(ic.rating), 1) as avg_rating
    FROM public."Inspections" i
    JOIN public."Buyback_Requests" br ON i.request_id = br.request_id
    JOIN public."Cars" c ON br.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    JOIN public."Employees" e ON i.inspector_id = e.employee_id
    LEFT JOIN public."Inspection_Checkpoints" ic ON i.inspection_id = ic.inspection_id
    GROUP BY i.inspection_id, br.request_id, b.name, m.name, c.vin_code, e.first_name, e.last_name
    ORDER BY i.inspection_date DESC;
    """
    hist_df = run_query(history_query, fetch="all")

    # Заповнюємо пусті рейтинги (якщо немає чекпоінтів) нулями
    if hist_df is not None and not hist_df.empty:
        hist_df['avg_rating'] = hist_df['avg_rating'].fillna(0)

    # 2. Інспектори
    insp_df = run_query(
        "SELECT employee_id, first_name || ' ' || last_name AS full_name FROM public.\"Employees\" WHERE is_active = true;",
        fetch="all")

    # 3. Заявки на черзі
    pending_query = """
    SELECT br.request_id, b.name || ' ' || m.name || ' (' || c.year || ')' AS car_desc
    FROM public."Buyback_Requests" br
    JOIN public."Cars" c ON br.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    WHERE br.status NOT IN ('completed', 'rejected')
      AND br.request_id NOT IN (SELECT request_id FROM public."Inspections")
    ORDER BY br.request_id ASC; 
    """
    pending_df = run_query(pending_query, fetch="all")

    return hist_df, insp_df, pending_df


history_df, inspectors_df, pending_requests_df = load_data()

# --- 🎨 САЙДБАР: ФІЛЬТРИ ---
st.sidebar.header("Фільтри")

search_q = st.sidebar.text_input("🔍 Пошук (VIN, ID):")

# Фільтри по бренду та моделі
all_brands = sorted(history_df['brand'].unique()) if history_df is not None and not history_df.empty else []
brand_filter = st.sidebar.multiselect("Марка:", options=all_brands)

# Фільтр по моделі (залежить від бренду)
if brand_filter:
    available_models = sorted(history_df[history_df['brand'].isin(brand_filter)]['model'].unique())
else:
    available_models = sorted(history_df['model'].unique()) if history_df is not None and not history_df.empty else []

model_filter = st.sidebar.multiselect("Модель:", options=available_models)

# Фільтр по рейтингу
rating_range = st.sidebar.slider("Рейтинг інспекції:", 1.0, 5.0, (1.0, 5.0), step=0.5)

# --- ЗАСТОСУВАННЯ ФІЛЬТРІВ ---
filtered_df = history_df.copy()

if search_q:
    mask = (
            filtered_df['car_info'].str.contains(search_q, case=False, na=False) |
            filtered_df['vin_code'].str.contains(search_q, case=False, na=False) |
            filtered_df['request_id'].astype(str).str.contains(search_q, case=False, na=False)
    )
    filtered_df = filtered_df[mask]

if brand_filter:
    filtered_df = filtered_df[filtered_df['brand'].isin(brand_filter)]

if model_filter:
    filtered_df = filtered_df[filtered_df['model'].isin(model_filter)]

# Фільтр по рейтингу
filtered_df = filtered_df[
    (filtered_df['avg_rating'] >= rating_range[0]) &
    (filtered_df['avg_rating'] <= rating_range[1])
    ]

# --- ВІДОБРАЖЕННЯ ТАБЛИЦІ ---
if filtered_df is not None and not filtered_df.empty:
    st.info(f"Знайдено звітів: {len(filtered_df)}")

    # Конфігурація колонок (гарні зірочки для рейтингу)
    st.dataframe(
        filtered_df,
        use_container_width=True,
        column_config={
            "avg_rating": st.column_config.NumberColumn(
                "Рейтинг",
                help="Середня оцінка стану авто (1-5)",
                format="%.1f ⭐"
            ),
            "inspection_date": st.column_config.DateColumn("Дата"),
        },
        column_order=["inspection_id", "avg_rating", "car_info", "inspector_name", "inspection_date",
                      "final_conclusion"]
    )
else:
    st.info("Інспекцій не знайдено.")

st.divider()

# --- CRUD ОПЕРАЦІЇ ---
st.subheader("🛠️ Управління")
operation = st.selectbox("Дія:", ["Провести нову інспекцію", "Переглянути деталі", "Видалити звіт"])

# ==========================================
# === CREATE ===
# ==========================================
if operation == "Провести нову інспекцію":
    if pending_requests_df is None or pending_requests_df.empty:
        st.success("Всі активні заявки перевірені!")
    else:
        with st.form("new_inspection"):
            st.write("### Новий звіт")
            c1, c2 = st.columns(2)

            req_id = c1.selectbox("Заявка:", options=pending_requests_df['request_id'],
                                  format_func=lambda x: f"ID {x} | " + pending_requests_df.loc[
                                      pending_requests_df['request_id'] == x, 'car_desc'].iloc[0])
            insp_id = c1.selectbox("Інспектор:", options=inspectors_df['employee_id'], format_func=lambda x:
            inspectors_df.loc[inspectors_df['employee_id'] == x, 'full_name'].iloc[0])
            insp_date = c2.date_input("Дата:", value=datetime.date.today())
            location = c2.text_input("Місце:", value="Головний офіс")

            st.markdown("---")
            results = {}
            for item in STANDARD_CHECKPOINTS:
                ca, cb = st.columns([1, 2])
                rating = ca.slider(f"{item}", 1, 5, 4)
                comment = cb.text_input(f"Коментар ({item})", placeholder="Ок")
                results[item] = (rating, comment)

            final_text = st.text_area("Висновок:", height=80)

            if st.form_submit_button("Зберегти"):
                try:
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """INSERT INTO "Inspections" (request_id, inspector_id, inspection_date, location, final_conclusion) VALUES (%s, %s, %s, %s, %s) RETURNING inspection_id;""",
                                (req_id, insp_id, insp_date, location, final_text))
                            new_id = cur.fetchone()[0]
                            for name, (rat, comm) in results.items():
                                cur.execute(
                                    """INSERT INTO "Inspection_Checkpoints" (inspection_id, checkpoint_name, rating, comment) VALUES (%s, %s, %s, %s);""",
                                    (new_id, name, rat, comm))
                            cur.execute(
                                "UPDATE \"Buyback_Requests\" SET status = 'inspection_scheduled' WHERE request_id = %s AND status = 'new';",
                                (req_id,))
                        conn.commit()
                    log_action(st.session_state['user_id'], "INSERT", "Inspections", new_id, f"Insp for Req {req_id}")
                    st.success("Збережено!");
                    st.cache_data.clear();
                    time.sleep(1);
                    st.rerun()
                except Exception as e:
                    st.error(f"Помилка: {e}")

# ==========================================
# === READ DETAILS ===
# ==========================================
elif operation == "Переглянути деталі":
    sel_id = st.selectbox("Оберіть інспекцію:", options=filtered_df['inspection_id'])  # Вибираємо з відфільтрованого

    if sel_id:
        row = history_df[history_df['inspection_id'] == sel_id].iloc[0]
        details = run_query(
            'SELECT checkpoint_name, rating, comment FROM "Inspection_Checkpoints" WHERE inspection_id=%s', (sel_id,),
            fetch="all")

        st.write("---")
        c1, c2 = st.columns([2, 1])
        with c1:
            if details is not None:
                def colorize(val):
                    return 'background-color: #d4edda; color: black' if val >= 4 else 'background-color: #fff3cd; color: black' if val == 3 else 'background-color: #f8d7da; color: black'


                st.dataframe(details.style.map(colorize, subset=['rating']), use_container_width=True)
        with c2:
            st.metric("Середній рейтинг", f"{row['avg_rating']} ⭐")
            st.info(f"**Авто:** {row['car_info']}\n\n**Інспектор:** {row['inspector_name']}")
            st.text_area("Висновок:", value=row['final_conclusion'], disabled=True)

# ==========================================
# === DELETE ===
# ==========================================
elif operation == "Видалити звіт":
    del_id = st.selectbox("Звіт для видалення:", options=filtered_df['inspection_id'])
    if st.button("🗑️ Видалити"):
        try:
            run_query('DELETE FROM "Inspections" WHERE inspection_id=%s', (del_id,), commit=True)
            log_action(st.session_state['user_id'], "DELETE", "Inspections", int(del_id), "Deleted report")
            st.success("Видалено.");
            st.cache_data.clear();
            time.sleep(1);
            st.rerun()
        except Exception as e:
            st.error(f"Помилка: {e}")