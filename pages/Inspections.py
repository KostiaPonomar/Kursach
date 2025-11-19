import streamlit as st
from db_utils import run_query, get_db_connection
import pandas as pd
import psycopg2
import time
from datetime import datetime

st.set_page_config(page_title="Технічні інспекції", layout="wide")
st.title("🔧 Технічні інспекції (Inspections)")

# Стандартний перелік вузлів для перевірки
STANDARD_CHECKPOINTS = [
    "Двигун (Engine)",
    "Коробка передач (Transmission)",
    "Ходова частина (Suspension)",
    "Кузов та ЛФП (Body & Paint)",
    "Салон (Interior)",
    "Електроніка (Electronics)"
]


# --- ЗАВАНТАЖЕННЯ ДАНИХ ---
@st.cache_data
def load_inspections_data():
    """Завантажує історію інспекцій та дані для створення нових."""

    # 1. Існуючі інспекції
    inspections_query = """
    SELECT 
        i.inspection_id,
        br.request_id,
        b.name || ' ' || m.name || ' (' || c.vin_code || ')' AS car_info,
        e.first_name || ' ' || e.last_name AS inspector_name,
        i.inspection_date,
        i.final_conclusion
    FROM public."Inspections" i
    JOIN public."Buyback_Requests" br ON i.request_id = br.request_id
    JOIN public."Cars" c ON br.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    JOIN public."Employees" e ON i.inspector_id = e.employee_id
    ORDER BY i.inspection_date DESC;
    """
    inspections = run_query(inspections_query, fetch="all")

    # 2. Співробітники (Інспектори)
    inspectors = run_query("""
        SELECT employee_id, first_name || ' ' || last_name AS full_name 
        FROM public."Employees" 
        WHERE is_active = true;
    """, fetch="all")

    # 3. Заявки, які потребують інспекції
    pending_requests_query = """
    SELECT 
        br.request_id,
        b.name || ' ' || m.name || ' (' || c.year || ')' AS car_desc
    FROM public."Buyback_Requests" br
    JOIN public."Cars" c ON br.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    WHERE br.status NOT IN ('completed', 'rejected')
      AND br.request_id NOT IN (SELECT request_id FROM public."Inspections")
    ORDER BY br.request_id ASC; 
    """
    pending_requests = run_query(pending_requests_query, fetch="all")

    return inspections, inspectors, pending_requests


inspections_df, inspectors_df, pending_requests_df = load_inspections_data()

# --- ГОЛОВНА ТАБЛИЦЯ ---
st.header("Історія інспекцій")
if inspections_df is not None and not inspections_df.empty:
    st.dataframe(inspections_df, use_container_width=True)
else:
    st.info("Інспекцій ще не проводилось.")

# --- CRUD ---
st.divider()
st.header("Управління")
operation = st.selectbox("Оберіть дію:", ["Провести нову інспекцію", "Переглянути деталі звіту", "Видалити звіт"])

# ==========================================
# === CREATE (ПРОВЕДЕННЯ ІНСПЕКЦІЇ) ===
# ==========================================
if operation == "Провести нову інспекцію":
    st.subheader("📝 Новий звіт інспекції")

    if pending_requests_df is None or pending_requests_df.empty:
        st.warning("Немає відкритих заявок, які потребують інспекції.")
    else:
        with st.form("create_inspection_form"):
            col1, col2 = st.columns(2)

            with col1:
                # --- ЗМІНИ ТУТ: ВИБІР ПО ID ---
                request_id = st.selectbox(
                    "Введіть або оберіть ID заявки:",
                    options=pending_requests_df['request_id'],
                    # Формат відображення: "ID 15 | BMW X5 (2020)"
                    format_func=lambda x: f"ID {x} | " + pending_requests_df.loc[
                        pending_requests_df['request_id'] == x, 'car_desc'].iloc[0]
                )

                inspector_id = st.selectbox(
                    "Інспектор:",
                    options=inspectors_df['employee_id'],
                    format_func=lambda x: inspectors_df.loc[inspectors_df['employee_id'] == x, 'full_name'].iloc[0]
                )

            with col2:
                insp_date = st.date_input("Дата інспекції:", value=datetime.today())
                location = st.text_input("Місце проведення:", value="СТО 'Головний Офіс'")

            st.markdown("### 🔍 Чек-лист перевірки")
            st.write("Оцініть стан вузлів від 1 (Жахливо) до 5 (Ідеально)")

            checkpoints_data = {}

            for cp_name in STANDARD_CHECKPOINTS:
                c1, c2 = st.columns([1, 3])
                with c1:
                    rating = st.slider(f"{cp_name}", 1, 5, 4, key=f"rate_{cp_name}")
                with c2:
                    comment = st.text_input(f"Коментар ({cp_name})", key=f"comm_{cp_name}", placeholder="Ок")
                checkpoints_data[cp_name] = {'rating': rating, 'comment': comment}

            final_conclusion = st.text_area("🏁 Фінальний висновок інспектора:", height=100)

            submitted = st.form_submit_button("Зберегти результати інспекції")

            if submitted:
                try:
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            # 1. Створення запису в Inspections
                            cur.execute("""
                                INSERT INTO public."Inspections" 
                                (request_id, inspector_id, inspection_date, location, final_conclusion)
                                VALUES (%s, %s, %s, %s, %s)
                                RETURNING inspection_id;
                            """, (request_id, inspector_id, insp_date, location, final_conclusion))

                            new_inspection_id = cur.fetchone()[0]

                            # 2. Запис чекпоінтів
                            for name, data in checkpoints_data.items():
                                cur.execute("""
                                    INSERT INTO public."Inspection_Checkpoints"
                                    (inspection_id, checkpoint_name, rating, comment)
                                    VALUES (%s, %s, %s, %s);
                                """, (new_inspection_id, name, data['rating'], data['comment']))

                            # 3. Оновлення статусу заявки на 'inspection_scheduled'
                            cur.execute("""
                                UPDATE public."Buyback_Requests" 
                                SET status = 'inspection_scheduled' 
                                WHERE request_id = %s AND status = 'new';
                            """, (request_id,))

                        conn.commit()

                    st.success(f"Інспекцію для заявки ID {request_id} успішно збережено!")
                    st.cache_data.clear()
                    time.sleep(2)
                    st.rerun()

                except psycopg2.Error as e:
                    st.error(f"Помилка бази даних: {e}")

# ==========================================
# === VIEW DETAILS (ПЕРЕГЛЯД) ===
# ==========================================
elif operation == "Переглянути деталі звіту":
    st.subheader("Деталі звіту")
    if inspections_df is not None and not inspections_df.empty:
        # Тут теж додамо ID для зручності
        sel_insp_id = st.selectbox(
            "Введіть ID інспекції:",
            options=inspections_df['inspection_id'],
            format_func=lambda x: f"ID {x} | " +
                                  inspections_df.loc[inspections_df['inspection_id'] == x, 'car_info'].iloc[0]
        )

        # Отримуємо пункти перевірки
        details = run_query("""
            SELECT checkpoint_name, rating, comment 
            FROM public."Inspection_Checkpoints"
            WHERE inspection_id = %s;
        """, (sel_insp_id,), fetch="all")

        insp_row = inspections_df[inspections_df['inspection_id'] == sel_insp_id].iloc[0]

        st.divider()
        col_info1, col_info2 = st.columns(2)
        with col_info1:
            st.markdown(f"**Авто:** {insp_row['car_info']}")
            st.markdown(f"**Інспектор:** {insp_row['inspector_name']}")
        with col_info2:
            st.markdown(f"**Дата:** {insp_row['inspection_date']}")
            st.markdown(f"**ID Заявки:** {insp_row['request_id']}")

        st.text_area("Фінальний висновок:", value=insp_row['final_conclusion'], disabled=True)

        if details is not None and not details.empty:
            st.markdown("### Результати діагностики")


            # Функція для кольорів
            def highlight_rating(val):
                if val >= 4:
                    color = '#d4edda'  # Greenish
                elif val == 3:
                    color = '#fff3cd'  # Yellowish
                else:
                    color = '#f8d7da'  # Reddish
                return f'background-color: {color}; color: black'


            st.dataframe(details.style.map(highlight_rating, subset=['rating']), use_container_width=True)
        else:
            st.warning("Деталі чек-листа відсутні.")

# ==========================================
# === DELETE (ВИДАЛЕННЯ) ===
# ==========================================
elif operation == "Видалити звіт":
    st.subheader("Видалення звіту")
    if inspections_df is not None and not inspections_df.empty:
        del_id = st.selectbox("Оберіть ID інспекції:", options=inspections_df['inspection_id'])

        if st.button("🗑️ Видалити звіт"):
            try:
                run_query('DELETE FROM public."Inspections" WHERE inspection_id = %s;', (del_id,))
                st.success("Звіт видалено.")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()
            except psycopg2.Error as e:
                st.error(f"Помилка: {e}")