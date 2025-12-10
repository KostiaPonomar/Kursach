import streamlit as st
from db_utils import run_query
from navigation import make_sidebar
import pandas as pd
import datetime

st.set_page_config(page_title="Протокол дій", layout="wide")

# --- 🔒 ЗАХИСТ ДОСТУПУ ---
if 'user_id' not in st.session_state or st.session_state['user_id'] is None:
    st.warning("Будь ласка, увійдіть в систему.")
    st.switch_page("main.py")
    st.stop()

if st.session_state['role'] != 'admin':
    st.error("⛔ Немає доступу! Ця сторінка тільки для Адміністраторів.")
    st.stop()

make_sidebar()
# ---------------------------------------

st.title("🛡️ Протокол дій (Audit Logs)")

# --- ФІЛЬТРИ ---
st.sidebar.header("Фільтрація логів")

today = datetime.date.today()
start_date = st.sidebar.date_input("З дати:", value=today - datetime.timedelta(days=7))
end_date = st.sidebar.date_input("По дату:", value=today)

action_types = ["Всі", "LOGIN", "REGISTER", "INSERT", "UPDATE", "DELETE", "TRANSACTION", "ARCHIVE", "MODERATE",
                "EXTERNAL_LEAD"]
selected_action = st.sidebar.selectbox("Тип дії:", action_types)

search_user = st.sidebar.text_input("Пошук (ID або Email):")

# --- ЗАВАНТАЖЕННЯ ---
base_query = """
    SELECT 
        al.log_id,
        al.timestamp,
        u.email AS user_email,
        u.role,
        al.action_type,
        al.table_name,
        al.record_id,
        al.details
    FROM public."Audit_Logs" al
    LEFT JOIN public."Users" u ON al.user_id = u.user_id
    WHERE al.timestamp BETWEEN %s AND %s
"""
params = [start_date, end_date + datetime.timedelta(days=1)]

if selected_action != "Всі":
    base_query += " AND al.action_type = %s"
    params.append(selected_action)

if search_user:
    base_query += " AND (u.email ILIKE %s OR CAST(al.user_id AS TEXT) = %s)"
    params.append(f"%{search_user}%")
    params.append(search_user)

base_query += " ORDER BY al.timestamp DESC LIMIT 500;"

logs_df = run_query(base_query, tuple(params), fetch="all")

# --- ВІДОБРАЖЕННЯ ---
if logs_df is not None and not logs_df.empty:
    st.info(f"Знайдено записів: {len(logs_df)}")


    def color_action(val):
        colors = {
            'DELETE': 'background-color: #ffcccc; color: black',  # Червоний фон, чорний текст
            'UPDATE': 'background-color: #fff4cc; color: black',  # Жовтий фон, чорний текст
            'INSERT': 'background-color: #ccffcc; color: black',  # Зелений фон, чорний текст
            'TRANSACTION': 'background-color: #d1c4e9; color: black',  # Фіолетовий фон, чорний текст
            'LOGIN': 'background-color: #e6f7ff; color: black',  # Синій фон, чорний текст
            'MODERATE': 'background-color: #ffecb3; color: black',  # Оранжевий фон, чорний текст
            'ARCHIVE': 'background-color: #e0e0e0; color: black',  # Сірий фон, чорний текст
            'EXTERNAL_LEAD': 'background-color: #b2dfdb; color: black'  # Бірюзовий фон, чорний текст
        }
        return colors.get(val, '')


    st.dataframe(
        logs_df.style.map(color_action, subset=['action_type']),
        use_container_width=True
    )

    st.divider()
    st.subheader("📥 Експорт протоколу")
    col1, col2 = st.columns(2)

    with col1:
        csv = logs_df.to_csv(index=False).encode('utf-8')
        st.download_button("Завантажити CSV", data=csv, file_name="audit.csv", mime="text/csv")

    with col2:
        json_str = logs_df.to_json(orient="records", force_ascii=False, date_format="iso")
        st.download_button("Завантажити JSON", data=json_str, file_name="audit.json", mime="application/json")

else:
    st.warning("Записів не знайдено за обраними критеріями.")