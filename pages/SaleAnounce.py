import streamlit as st
from db_utils import run_query
import pandas as pd
import time

st.set_page_config(page_title="Оголошення", layout="wide")
st.title("📢 Оголошення про продаж (активні)")


@st.cache_data
def load_data():
    """Завантажує всі активні оголошення з пов'язаними даними."""
    query = """
    SELECT 
        sa.announcement_id,
        b.name AS brand,
        m.name AS model,
        u.email AS owner_email,
        sa.price,
        sa.description,
        sa.creation_date
    FROM public."Sale_Announcements" sa
    JOIN public."Cars" c ON sa.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    JOIN public."Users" u ON sa.seller_user_id = u.user_id
    WHERE sa.status = 'active'
    ORDER BY sa.creation_date DESC;
    """
    return run_query(query, fetch="all")


data = load_data()

# Перевіряємо, чи дані завантажились
if data is None or data.empty:
    st.warning("Активних оголошень не знайдено.")
    st.stop()

# --- ФІЛЬТРИ ТА ПОШУК ---
st.sidebar.header("Фільтри та пошук")
brand_filter = st.sidebar.multiselect("Марка:", options=sorted(list(data['brand'].unique())))
min_price, max_price = int(data['price'].min()), int(data['price'].max())
col1, col2 = st.sidebar.columns(2)
with col1:
    price_from = st.number_input("Ціна від ($)", min_value=min_price, max_value=max_price, value=min_price, step=1000)
with col2:
    price_to = st.number_input("Ціна до ($)", min_value=min_price, max_value=max_price, value=max_price, step=1000)
search_query = st.sidebar.text_input("Пошук в описі:")

# Застосування фільтрів
filtered_data = data.copy()
if brand_filter:
    filtered_data = filtered_data[filtered_data['brand'].isin(brand_filter)]
if price_from > price_to:
    st.sidebar.error("Ціна 'від' не може бути більшою за ціну 'до'.")
else:
    filtered_data = filtered_data[(filtered_data['price'] >= price_from) & (filtered_data['price'] <= price_to)]
if search_query:
    filtered_data = filtered_data[filtered_data['description'].str.contains(search_query, case=False, na=False)]

st.dataframe(filtered_data, use_container_width=True)
st.info(f"Знайдено {len(filtered_data)} оголошень за вашими критеріями.")

if filtered_data.empty:
    st.stop()

# --- ПЕРЕГЛЯД ХАРАКТЕРИСТИК ---
st.header("Детальна інформація")
selected_ann_id_for_details = st.selectbox("Оберіть ID оголошення для перегляду характеристик:", options=filtered_data['announcement_id'])
if selected_ann_id_for_details:
    car_id_result = run_query("SELECT car_id FROM public.\"Sale_Announcements\" WHERE announcement_id = %s", (selected_ann_id_for_details,), fetch="one")
    if car_id_result:
        car_id = car_id_result[0]
        char_df = run_query("""SELECT ch.name, cc.value FROM public."Car_Characteristics" cc
                               JOIN public."Characteristics" ch ON cc.characteristic_id = ch.characteristic_id
                               WHERE cc.car_id = %s;""", (car_id,), fetch="all")
        with st.expander("Показати/сховати характеристики"):
            if char_df is not None and not char_df.empty:
                st.table(char_df)
            else:
                st.info("Для цього автомобіля характеристики не вказані.")

# --- УПРАВЛІННЯ ОГОЛОШЕННЯМ ---
st.header("Управління оголошенням")
operation = st.selectbox("Оберіть операцію:", ["Редагувати", "Архівувати (Видалити)"])

if operation == "Редагувати":
    st.subheader("Редагувати оголошення")
    ann_to_update = st.selectbox("Оберіть ID оголошення для редагування:", options=filtered_data['announcement_id'], key="upd_ann")
    if ann_to_update:
        current_data_row = data[data['announcement_id'] == ann_to_update].iloc[0]
        with st.form("update_ann_form"):
            new_price = st.number_input("Нова ціна:", value=float(current_data_row['price']))
            new_description = st.text_area("Новий опис:", value=current_data_row['description'])
            if st.form_submit_button("Оновити оголошення"):
                run_query('UPDATE public."Sale_Announcements" SET price = %s, description = %s WHERE announcement_id = %s;', (new_price, new_description, ann_to_update))
                st.success(f"Оголошення ID {ann_to_update} успішно оновлено!")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()

elif operation == "Архівувати (Видалити)":
    st.subheader("Архівувати оголошення")
    # --- ВИПРАВЛЕННЯ ТУТ: Використовуємо узгоджену назву змінної ---
    ann_to_archive = st.selectbox("Оберіть ID оголошення для архівування:", options=filtered_data['announcement_id'], key="archive_ann")
    if st.button("Архівувати оголошення"):
        run_query('UPDATE public."Sale_Announcements" SET status = %s WHERE announcement_id = %s;', ('archived', ann_to_archive))
        st.success(f"Оголошення {ann_to_archive} архівовано!")
        st.cache_data.clear()
        time.sleep(1)
        st.rerun()