import streamlit as st
from db_utils import run_query, get_db_connection
import pandas as pd
import psycopg2
import time

st.set_page_config(page_title="Угоди", layout="wide")
st.title("📈 Управління угодами (Deals)")


# --- ФУНКЦІЇ ДЛЯ ЗАВАНТАЖЕННЯ ДАНИХ ---
@st.cache_data
def load_deals_and_users():
    """Завантажує список угод та користувачів (для випадаючих списків)."""

    # 1. Список угод (для таблиці)
    # ДОДАНО: b.name AS brand_name (щоб по ньому фільтрувати)
    deals_query = """
    SELECT
        d.deal_id,
        b.name AS brand_name, 
        b.name || ' ' || m.name || ' (' || c.year || ')' AS car_description,
        b_user.email AS buyer_email,
        s_user.email AS seller_email,
        d.final_price,
        d.deal_date,
        d.status
    FROM public."Deals" d
    JOIN public."Users" b_user ON d.buyer_user_id = b_user.user_id
    JOIN public."Sale_Announcements" sa ON d.announcement_id = sa.announcement_id
    JOIN public."Users" s_user ON sa.seller_user_id = s_user.user_id
    JOIN public."Cars" c ON sa.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    ORDER BY d.deal_date DESC;
    """
    deals = run_query(deals_query, fetch="all")

    # 2. Список користувачів (тільки для вибору покупця)
    users = run_query('SELECT user_id, email FROM public."Users" ORDER BY email;', fetch="all")

    return deals, users


deals_df, users_df = load_deals_and_users()

if deals_df is None:
    st.error("Не вдалося завантажити дані про угоди.")
    st.stop()

# --- БІЧНА ПАНЕЛЬ: ФІЛЬТРИ ТА ПОШУК ---
st.sidebar.header("Фільтри угод")

# 1. Фільтр по марці (НОВЕ)
# Отримуємо унікальні марки з завантажених даних
if not deals_df.empty:
    unique_brands = sorted(deals_df['brand_name'].unique().tolist())
    brand_options = ["Всі"] + unique_brands
    selected_brand = st.sidebar.selectbox("Марка авто:", options=brand_options)
else:
    selected_brand = "Всі"

# 2. Пошук по тексту
search_query = st.sidebar.text_input("Пошук (email):")

# 3. Фільтр по ціні
if not deals_df.empty:
    min_price, max_price = int(deals_df['final_price'].min()), int(deals_df['final_price'].max())
    # Перевірка, щоб мін і макс не були однаковими (якщо одна угода)
    if min_price == max_price:
        price_from, price_to = min_price, max_price
        st.sidebar.info(f"Фіксована ціна угод: ${min_price}")
    else:
        price_from = st.sidebar.number_input("Ціна від ($)", min_value=min_price, max_value=max_price, value=min_price)
        price_to = st.sidebar.number_input("Ціна до ($)", min_value=min_price, max_value=max_price, value=max_price)
else:
    price_from, price_to = 0, 100000

# --- ЗАСТОСУВАННЯ ФІЛЬТРІВ ---
filtered_df = deals_df.copy()

# Фільтр по Марці
if selected_brand != "Всі":
    filtered_df = filtered_df[filtered_df['brand_name'] == selected_brand]

# Фільтр по Пошуку
if search_query:
    mask = (filtered_df['buyer_email'].str.contains(search_query, case=False) | filtered_df[
        'seller_email'].str.contains(search_query, case=False))
    filtered_df = filtered_df[mask]

# Фільтр по Ціні
if not deals_df.empty and price_from <= price_to:
    filtered_df = filtered_df[(filtered_df['final_price'] >= price_from) & (filtered_df['final_price'] <= price_to)]

# Відображення таблиці
st.dataframe(filtered_df, use_container_width=True)
st.caption(f"Відображено {len(filtered_df)} із {len(deals_df)} угод.")

# --- CRUD ОПЕРАЦІЇ (Без змін, але включені для повноти) ---
st.header("Управління")
operation = st.selectbox("Оберіть дію:", ["Створити угоду", "Оновити статус", "Видалити угоду"])

# ==========================================
# === СТВОРЕННЯ УГОДИ (ПОШУК ЗА ID) ===
# ==========================================
if operation == "Створити угоду":
    st.subheader("Крок 1: Пошук оголошення")

    col_search1, col_search2 = st.columns([3, 1])
    with col_search1:
        announcement_id_input = st.number_input("Введіть ID оголошення:", min_value=1, step=1, value=None,
                                                placeholder="Наприклад: 10")
    with col_search2:
        st.write("")
        st.write("")
        search_btn = st.button("🔍 Знайти", type="primary")

    if search_btn and announcement_id_input:
        query = """
            SELECT 
                sa.announcement_id, 
                sa.title, 
                sa.price, 
                sa.status, 
                sa.seller_user_id, 
                u.email as seller_email,
                c.vin_code,
                c.car_id
            FROM public."Sale_Announcements" sa
            JOIN public."Users" u ON sa.seller_user_id = u.user_id
            JOIN public."Cars" c ON sa.car_id = c.car_id
            WHERE sa.announcement_id = %s;
        """
        found_announcement = run_query(query, (announcement_id_input,), fetch="one")

        if found_announcement:
            st.session_state['deal_announcement'] = found_announcement
            if 'deal_buyer_id' in st.session_state: del st.session_state['deal_buyer_id']
        else:
            st.error(f"Оголошення з ID {announcement_id_input} не знайдено.")
            if 'deal_announcement' in st.session_state: del st.session_state['deal_announcement']

    if 'deal_announcement' in st.session_state:
        ann = st.session_state['deal_announcement']
        ann_id, title, price, status, seller_id, seller_email, vin, car_id = ann

        st.divider()
        st.markdown(f"### 🚘 Авто: {title}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ID Оголошення", ann_id)
        c2.metric("Ціна в оголошенні", f"${price:,.2f}")
        c3.metric("Продавець", seller_email)
        c4.metric("Статус", status, delta_color="normal" if status == 'active' else "inverse")

        if status != 'active':
            st.warning("⛔ Це оголошення не активне! Ви не можете створити угоду.")
        else:
            st.subheader("Крок 2: Оформлення угоди")

            with st.form("finalize_deal_form"):
                buyer_id = st.selectbox(
                    "Оберіть покупця (email):",
                    options=users_df['user_id'],
                    format_func=lambda x: users_df.loc[users_df['user_id'] == x, 'email'].iloc[0]
                )

                final_price = st.number_input("Фінальна ціна угоди ($):", value=float(price), min_value=0.0)

                if st.form_submit_button("✅ Підтвердити угоду"):
                    if buyer_id == seller_id:
                        st.error("Помилка: Продавець і покупець не можуть бути однією особою!")
                    else:
                        try:
                            with get_db_connection() as conn:
                                with conn.cursor() as cur:
                                    cur.execute(
                                        'INSERT INTO public."Deals" (announcement_id, buyer_user_id, final_price) VALUES (%s, %s, %s);',
                                        (ann_id, buyer_id, final_price))
                                    cur.execute(
                                        "UPDATE public.\"Sale_Announcements\" SET status = 'sold' WHERE announcement_id = %s;",
                                        (ann_id,))
                                    cur.execute("UPDATE public.\"Cars\" SET owner_id = %s WHERE car_id = %s;",
                                                (buyer_id, car_id))
                                conn.commit()

                            st.success("Угоду успішно укладено! Власника авто змінено.")
                            del st.session_state['deal_announcement']
                            st.cache_data.clear()
                            time.sleep(2)
                            st.rerun()
                        except psycopg2.Error as e:
                            st.error(f"Помилка транзакції: {e}")

# === ОНОВЛЕННЯ СТАТУСУ ===
elif operation == "Оновити статус":
    st.subheader("Редагування статусу угоди")
    if not filtered_df.empty:
        deal_to_update_id = st.selectbox("Оберіть ID угоди:", options=filtered_df['deal_id'])
        current_status = filtered_df[filtered_df['deal_id'] == deal_to_update_id]['status'].iloc[0]
        new_status = st.selectbox("Новий статус:", options=['completed', 'cancelled'],
                                  index=0 if current_status == 'completed' else 1)

        if st.button("Зберегти статус"):
            run_query('UPDATE public."Deals" SET status = %s WHERE deal_id = %s;', (new_status, deal_to_update_id))
            st.success(f"Статус оновлено на '{new_status}'")
            st.cache_data.clear()
            time.sleep(1)
            st.rerun()
    else:
        st.info("Список угод порожній (або фільтр приховав усі записи).")

# === ВИДАЛЕННЯ ===
elif operation == "Видалити угоду":
    st.subheader("Видалення запису про угоду")
    if not filtered_df.empty:
        deal_to_delete_id = st.selectbox("Оберіть ID угоди для видалення:", options=filtered_df['deal_id'])
        if st.button("🗑️ Видалити угоду"):
            try:
                run_query('DELETE FROM public."Deals" WHERE deal_id = %s;', (deal_to_delete_id,))
                st.success(f"Угоду ID {deal_to_delete_id} видалено!")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()
            except psycopg2.Error as e:
                st.error(f"Помилка видалення: {e}")
    else:
        st.info("Немає угод для видалення.")