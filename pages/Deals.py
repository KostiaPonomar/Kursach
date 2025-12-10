import streamlit as st
from db_utils import run_query, log_action, get_db_connection
from navigation import make_sidebar
import pandas as pd
import time

st.set_page_config(page_title="Угоди", layout="wide")

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

st.title("🤝 Управління угодами (Deals)")


# --- ЗАВАНТАЖЕННЯ ДАНИХ ---
@st.cache_data
def load_data():
    # 1. Історія угод (ВИПРАВЛЕНО: ДОДАНО model_name)
    deals_query = """
    SELECT
        d.deal_id,
        b.name AS brand_name, 
        m.name AS model_name,  -- <--- ОСЬ ЦЬОГО НЕ ВИСТАЧАЛО
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

    # 2. Активні оголошення (Для створення)
    active_anns_query = """
    SELECT 
        sa.announcement_id, 
        b.name || ' ' || m.name AS title,
        c.vin_code,
        u.email as seller_email,
        sa.price,
        sa.seller_user_id,
        c.car_id
    FROM public."Sale_Announcements" sa
    JOIN public."Cars" c ON sa.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    JOIN public."Users" u ON sa.seller_user_id = u.user_id
    WHERE sa.status = 'active'
    ORDER BY sa.announcement_id DESC;
    """
    anns = run_query(active_anns_query, fetch="all")

    # 3. Користувачі (Покупці)
    users = run_query('SELECT user_id, email FROM public."Users" ORDER BY email;', fetch="all")

    return deals, anns, users


deals_df, active_anns_df, users_df = load_data()

if deals_df is None:
    st.error("Помилка завантаження даних.")
    st.stop()

# --- 🎨 САЙДБАР: ФІЛЬТРИ ---
st.sidebar.header("Фільтри історії")

# 1. Пошук
search_query = st.sidebar.text_input("🔍 Пошук (Email, Авто):")

# 2. Бренд
all_brands = sorted(deals_df['brand_name'].unique()) if not deals_df.empty else []
brand_filter = st.sidebar.multiselect("Марка:", options=all_brands)

# 3. Модель (Залежний фільтр)
if brand_filter:
    available_models = sorted(deals_df[deals_df['brand_name'].isin(brand_filter)]['model_name'].unique())
else:
    # Тепер це працюватиме, бо колонка model_name існує
    available_models = sorted(deals_df['model_name'].unique()) if not deals_df.empty else []

model_filter = st.sidebar.multiselect("Модель:", options=available_models)

# 4. Ціна (Фінальна ціна угоди)
if not deals_df.empty:
    min_p = int(deals_df['final_price'].min())
    max_p = int(deals_df['final_price'].max())
else:
    min_p, max_p = 0, 100000

c_p1, c_p2 = st.sidebar.columns(2)
price_from = c_p1.number_input("Ціна від ($)", min_value=0, value=min_p, step=500)
price_to = c_p2.number_input("Ціна до ($)", min_value=0, value=max_p, step=500)

# --- ЗАСТОСУВАННЯ ФІЛЬТРІВ ---
filtered_df = deals_df.copy()

if search_query:
    mask = (
            filtered_df['buyer_email'].str.contains(search_query, case=False) |
            filtered_df['seller_email'].str.contains(search_query, case=False) |
            filtered_df['car_description'].str.contains(search_query, case=False)
    )
    filtered_df = filtered_df[mask]

if brand_filter:
    filtered_df = filtered_df[filtered_df['brand_name'].isin(brand_filter)]

if model_filter:
    filtered_df = filtered_df[filtered_df['model_name'].isin(model_filter)]

# Фільтр по ціні
filtered_df = filtered_df[(filtered_df['final_price'] >= price_from) & (filtered_df['final_price'] <= price_to)]

# --- ВІДОБРАЖЕННЯ ---
st.subheader("📜 Історія угод")

if not filtered_df.empty:
    # Вибираємо колонки для показу (ховаємо технічні brand_name та model_name)
    display_cols = ['deal_id', 'car_description', 'final_price', 'buyer_email', 'seller_email', 'deal_date', 'status']

    st.dataframe(
        filtered_df[display_cols],
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("Історія порожня або нічого не знайдено.")

st.divider()

# --- CRUD ОПЕРАЦІЇ ---
st.subheader("🛠️ Операції")
operation = st.selectbox("Оберіть дію:", ["Оформити нову угоду", "Змінити статус угоди", "Видалити запис"])

# ==========================================
# === CREATE (ТРАНЗАКЦІЯ) ===
# ==========================================
if operation == "Оформити нову угоду":
    if active_anns_df is None or active_anns_df.empty:
        st.warning("Немає активних оголошень для продажу.")
    else:
        st.write("### Оформлення продажу")


        # Пошук оголошення
        def format_ann(id):
            row = active_anns_df[active_anns_df['announcement_id'] == id].iloc[0]
            return f"ID {id} | {row['title']} | ${row['price']} | Продавець: {row['seller_email']}"


        ann_id = st.selectbox("Оберіть активне оголошення:", options=active_anns_df['announcement_id'],
                              format_func=format_ann)

        # Отримуємо дані вибраного авто
        sel_ann = active_anns_df[active_anns_df['announcement_id'] == ann_id].iloc[0]

        st.info(f"Вибрано: **{sel_ann['title']}** (VIN: {sel_ann['vin_code']})")

        with st.form("create_deal"):
            c1, c2 = st.columns(2)
            buyer_id = c1.selectbox(
                "Покупець:",
                options=users_df['user_id'],
                format_func=lambda x: users_df.loc[users_df['user_id'] == x, 'email'].iloc[0]
            )
            final_price = c2.number_input("Фінальна ціна угоди ($):", value=float(sel_ann['price']), min_value=0.0)

            if st.form_submit_button("✅ Підтвердити угоду"):
                if buyer_id == sel_ann['seller_user_id']:
                    st.error("Помилка: Продавець не може купити авто сам у себе!")
                else:
                    try:
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                # 1. Створення Deal
                                cur.execute(
                                    'INSERT INTO public."Deals" (announcement_id, buyer_user_id, final_price) VALUES (%s, %s, %s) RETURNING deal_id;',
                                    (int(ann_id), buyer_id, final_price)
                                )
                                new_deal_id = cur.fetchone()[0]

                                # 2. Закриття Оголошення
                                cur.execute(
                                    "UPDATE public.\"Sale_Announcements\" SET status = 'sold' WHERE announcement_id = %s;",
                                    (int(ann_id),))

                                # 3. Зміна Власника авто
                                cur.execute("UPDATE public.\"Cars\" SET owner_id = %s WHERE car_id = %s;",
                                            (buyer_id, int(sel_ann['car_id'])))

                            conn.commit()

                        log_action(st.session_state['user_id'], "TRANSACTION", "Deals", new_deal_id,
                                   f"Продаж авто ID {sel_ann['car_id']}")
                        st.cache_data.clear()  # Очистка кешу
                        st.balloons()
                        st.success(f"Угоду #{new_deal_id} успішно оформлено! Власника змінено.")
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Помилка транзакції: {e}")

# ==========================================
# === UPDATE ===
# ==========================================
elif operation == "Змінити статус угоди":
    if not deals_df.empty:
        deal_id = st.selectbox("Оберіть угоду:", options=deals_df['deal_id'])
        if deal_id:
            curr_status = deals_df[deals_df['deal_id'] == deal_id]['status'].iloc[0]
            status_opts = ['completed', 'cancelled', 'pending']
            # Перевірка наявності статусу в списку
            idx = status_opts.index(curr_status) if curr_status in status_opts else 0

            new_status = st.selectbox("Новий статус:", status_opts, index=idx)

            if st.button("Оновити статус"):
                run_query('UPDATE public."Deals" SET status=%s WHERE deal_id=%s', (new_status, deal_id), commit=True)
                log_action(st.session_state['user_id'], "UPDATE", "Deals", int(deal_id), f"Статус: {new_status}")
                st.cache_data.clear()
                st.success("Оновлено.")
                time.sleep(1)
                st.rerun()
    else:
        st.warning("Історія порожня.")

# ==========================================
# === DELETE ===
# ==========================================
elif operation == "Видалити запис":
    if not deals_df.empty:
        deal_id = st.selectbox("Оберіть угоду для видалення:", options=deals_df['deal_id'])
        st.warning("⚠️ Видалення запису не скасовує зміну власності авто!")

        if st.button("🗑️ Видалити"):
            try:
                run_query('DELETE FROM public."Deals" WHERE deal_id=%s', (deal_id,), commit=True)
                log_action(st.session_state['user_id'], "DELETE", "Deals", int(deal_id), "Видалено запис про угоду")
                st.cache_data.clear()
                st.success("Видалено.")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Помилка: {e}")
    else:
        st.warning("Історія порожня.")