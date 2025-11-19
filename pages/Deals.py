import streamlit as st
from db_utils import run_query, get_db_connection
import pandas as pd
import psycopg2
import time

st.set_page_config(page_title="Угоди", layout="wide")
st.title("📈 Управління угодами (Deals)")


# --- ФУНКЦІЇ ДЛЯ ЗАВАНТАЖЕННЯ ДАНИХ ---
@st.cache_data
def load_all_deals_data():
    """Завантажує всі угоди та дані для форм."""
    # Запит для основної таблиці угод залишається без змін
    deals_query = """
    SELECT
        d.deal_id,
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

    # --- ОНОВЛЕНИЙ ЗАПИТ ДЛЯ ОГОЛОШЕНЬ ---
    active_announcements_query = """
    SELECT 
        sa.announcement_id, 
        -- Створюємо рядок у форматі "ID: Марка Модель (Рік) - $Ціна"
        sa.announcement_id || ': ' || b.name || ' ' || m.name || ' (' || c.year || ')' || ' - $' || sa.price AS announcement_info,
        sa.price
    FROM public."Sale_Announcements" sa
    JOIN public."Cars" c ON sa.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    WHERE sa.status = 'active';
    """
    active_announcements = run_query(active_announcements_query, fetch="all")

    users = run_query('SELECT user_id, email FROM public."Users";', fetch="all")

    return deals, active_announcements, users


deals_df, announcements_df, users_df = load_all_deals_data()

if deals_df is None:
    st.error("Не вдалося завантажити дані про угоди.")
    st.stop()

# --- БІЧНА ПАНЕЛЬ: ФІЛЬТРИ ТА ПОШУК ---
st.sidebar.header("Фільтри та пошук")
search_query = st.sidebar.text_input("Пошук (за email покупця/продавця):")
if not deals_df.empty:
    min_price, max_price = int(deals_df['final_price'].min()), int(deals_df['final_price'].max())
    price_from = st.sidebar.number_input("Ціна від ($)", min_value=min_price, max_value=max_price, value=min_price)
    price_to = st.sidebar.number_input("Ціна до ($)", min_value=min_price, max_value=max_price, value=max_price)
else:
    price_from, price_to = 0, 100000

filtered_df = deals_df.copy()
if search_query:
    mask = (filtered_df['buyer_email'].str.contains(search_query, case=False) | filtered_df[
        'seller_email'].str.contains(search_query, case=False))
    filtered_df = filtered_df[mask]
if not deals_df.empty and price_from <= price_to:
    filtered_df = filtered_df[(filtered_df['final_price'] >= price_from) & (filtered_df['final_price'] <= price_to)]

st.dataframe(filtered_df, use_container_width=True)
st.info(f"Знайдено {len(filtered_df)} угод.")

if filtered_df.empty and not search_query:
    st.stop()

# --- CRUD ОПЕРАЦІЇ ---
st.header("CRUD Операції")
operation = st.selectbox("Оберіть операцію:", ["Створити", "Оновити статус", "Видалити"])

# === CREATE ===
if operation == "Створити":
    st.subheader("Створити нову угоду")

    if announcements_df is not None and not announcements_df.empty:
        # Пошук винесено за межі форми для стабільності
        search_announcement = st.text_input("Почніть вводити ID, марку, модель або рік для пошуку оголошення:")

        available_announcements = announcements_df[
            announcements_df['announcement_info'].str.contains(search_announcement, case=False)
        ] if search_announcement else announcements_df

        if available_announcements.empty:
            st.warning("За вашим пошуковим запитом оголошень не знайдено.")
        else:
            with st.form("create_deal_form", clear_on_submit=True):
                announcement_id = st.selectbox(
                    "Активне оголошення (ID: Марка Модель (Рік) - $Ціна):",
                    options=available_announcements['announcement_id'],
                    format_func=lambda x: available_announcements.loc[
                        available_announcements['announcement_id'] == x, 'announcement_info'].iloc[0]
                )

                default_price = available_announcements.loc[
                    available_announcements['announcement_id'] == announcement_id, 'price'].iloc[0]
                final_price = st.number_input("Фінальна ціна (Final Price):", value=float(default_price), min_value=0.0)

                buyer_id = st.selectbox("Покупець (за email):", options=users_df['user_id'],
                                        format_func=lambda x: users_df.loc[users_df['user_id'] == x, 'email'].iloc[0])

                if st.form_submit_button("Створити угоду"):
                    try:
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                # --- ПОЧАТОК ТРАНЗАКЦІЇ ---

                                # Крок 1: Створюємо запис в Deals
                                cur.execute(
                                    'INSERT INTO public."Deals" (announcement_id, buyer_user_id, final_price) VALUES (%s, %s, %s);',
                                    (announcement_id, buyer_id, final_price))

                                # Крок 2: Оновлюємо статус оголошення
                                cur.execute(
                                    "UPDATE public.\"Sale_Announcements\" SET status = 'sold' WHERE announcement_id = %s;",
                                    (announcement_id,))

                                # Крок 3: Змінюємо власника автомобіля
                                cur.execute(
                                    "SELECT car_id FROM public.\"Sale_Announcements\" WHERE announcement_id = %s;",
                                    (announcement_id,))
                                car_id_to_update = cur.fetchone()[0]
                                cur.execute("UPDATE public.\"Cars\" SET owner_id = %s WHERE car_id = %s;",
                                            (buyer_id, car_id_to_update))

                            conn.commit()
                            # --- КІНЕЦЬ ТРАНЗАКЦІЇ ---

                        st.success(f"Угоду для оголошення ID {announcement_id} успішно створено! Власника змінено.")
                        st.cache_data.clear()
                        time.sleep(2)
                        st.rerun()
                    except psycopg2.Error as e:
                        st.error(f"Помилка бази даних: {e}")
    else:
        st.warning("Немає активних оголошень для створення угод.")


# === UPDATE ===
elif operation == "Оновити статус":
    st.subheader("Оновити статус угоди")
    deal_to_update_id = st.selectbox("Оберіть ID угоди для оновлення:", options=filtered_df['deal_id'])
    new_status = st.selectbox("Новий статус:", options=['completed', 'cancelled'])
    if st.button("Оновити"):
        run_query('UPDATE public."Deals" SET status = %s WHERE deal_id = %s;', (new_status, deal_to_update_id))
        st.success(f"Статус угоди ID {deal_to_update_id} оновлено!")
        st.cache_data.clear()
        st.rerun()

# === DELETE ===
elif operation == "Видалити":
    st.subheader("Видалити угоду")
    st.warning("Видалення угоди є незворотною дією. Краще скасовувати угоду (Update status to 'cancelled').")
    deal_to_delete_id = st.selectbox("Оберіть ID угоди для видалення:", options=filtered_df['deal_id'])
    if st.button("Видалити назавжди"):
        try:
            run_query('DELETE FROM public."Deals" WHERE deal_id = %s;', (deal_to_delete_id,))
            st.success(f"Угоду ID {deal_to_delete_id} видалено!")
            st.cache_data.clear()
            st.rerun()
        except psycopg2.Error as e:
            st.error(f"Помилка видалення: {e}")