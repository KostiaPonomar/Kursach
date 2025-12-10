import streamlit as st
from db_utils import run_query, log_action, get_db_connection
from navigation import make_sidebar
import pandas as pd
import time

st.set_page_config(page_title="Оголошення", layout="wide")

# --- 🔒 ЗАХИСТ ДОСТУПУ ---
if 'user_id' not in st.session_state or st.session_state['user_id'] is None:
    st.warning("Будь ласка, увійдіть в систему.")
    st.switch_page("main.py")
    st.stop()

make_sidebar()
# -------------------------

st.title("📢 Вітрина оголошень")


# --- ЗАВАНТАЖЕННЯ ДАНИХ ---
@st.cache_data
def load_data():
    # 1. Оголошення
    query = """
    SELECT 
        sa.announcement_id,
        b.name AS brand,
        m.name AS model,
        c.year,
        c.mileage,
        u.email AS owner_email,
        u.phone_number AS owner_phone,
        sa.seller_user_id,
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
    df = run_query(query, fetch="all")

    # 2. Довідник характеристик
    chars_ref = run_query('SELECT characteristic_id, name FROM public."Characteristics" ORDER BY name;', fetch="all")

    return df, chars_ref


df, chars_ref_df = load_data()

if df is None:
    st.error("Помилка завантаження оголошень.")
    st.stop()

# --- 🎨 САЙДБАР: ФІЛЬТРИ ---
st.sidebar.header("Фільтри")

# === ЛОГІКА ЧЕКБОКСУ ===
user_role = str(st.session_state.get('role', 'client')).lower()

if user_role == 'client':
    if st.sidebar.checkbox("👤 Показати тільки мої оголошення", key="filter_my_ads"):
        df = df[df['seller_user_id'] == st.session_state['user_id']]

elif user_role in ['manager', 'admin']:
    if st.sidebar.checkbox("🏢 Показати авто компанії", key="filter_company_ads"):
        comp_res = run_query("SELECT user_id FROM public.\"Users\" WHERE email = 'company@marketplace.com'",
                             fetch="one")
        comp_id = comp_res[0] if comp_res else -1
        df = df[df['seller_user_id'] == comp_id]

# === ІНШІ ФІЛЬТРИ ===
search_q = st.sidebar.text_input("🔍 Пошук (Опис):", key="search_q")

# 1. Бренд
all_brands = sorted(df['brand'].unique()) if not df.empty else []
brand_filter = st.sidebar.multiselect("Марка:", options=all_brands, key="brand_filter")

# 2. Модель (Залежний фільтр)
if brand_filter:
    # Якщо обрали марку - показуємо тільки її моделі
    available_models = sorted(df[df['brand'].isin(brand_filter)]['model'].unique())
else:
    # Інакше всі моделі
    available_models = sorted(df['model'].unique()) if not df.empty else []

model_filter = st.sidebar.multiselect("Модель:", options=available_models, key="model_filter")

# 3. Ціна
if not df.empty:
    min_p_db = int(df['price'].min())
    max_p_db = int(df['price'].max())
else:
    min_p_db, max_p_db = 0, 100000

c_p1, c_p2 = st.sidebar.columns(2)
p_from = c_p1.number_input("Від ($)", min_value=0, value=min_p_db, step=500, key="price_from")
p_to = c_p2.number_input("До ($)", min_value=0, value=max_p_db, step=500, key="price_to")

# --- ЗАСТОСУВАННЯ ФІЛЬТРІВ ---
filtered_df = df.copy()

if search_q:
    mask = (
            filtered_df['brand'].str.contains(search_q, case=False) |
            filtered_df['model'].str.contains(search_q, case=False) |
            filtered_df['description'].str.contains(search_q, case=False)
    )
    filtered_df = filtered_df[mask]

if brand_filter:
    filtered_df = filtered_df[filtered_df['brand'].isin(brand_filter)]

if model_filter:
    filtered_df = filtered_df[filtered_df['model'].isin(model_filter)]

filtered_df = filtered_df[(filtered_df['price'] >= p_from) & (filtered_df['price'] <= p_to)]

# --- ВІДОБРАЖЕННЯ ---
st.info("👇 Натисніть на рядок у таблиці, щоб побачити деталі.")
display_cols = ['brand', 'model', 'year', 'mileage', 'price', 'description']

event = st.dataframe(
    filtered_df[display_cols],
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row"
)

st.divider()

# --- ОТРИМАННЯ ВИБРАНОГО ID ---
sel_ann_id = None
if len(event.selection.rows) > 0:
    selected_index = event.selection.rows[0]
    sel_ann_id = filtered_df.iloc[selected_index]['announcement_id']

# --- ДЕТАЛІ ---
if sel_ann_id:
    car_id = \
    run_query('SELECT car_id FROM "Sale_Announcements" WHERE announcement_id=%s', (int(sel_ann_id),), fetch="one")[0]
    curr_ann = filtered_df[filtered_df['announcement_id'] == sel_ann_id].iloc[0]

    c1, c2 = st.columns([1, 1])

    with c1:
        st.subheader("ℹ️ Деталі авто")
        chars = run_query("""
            SELECT ch.name, cc.value 
            FROM "Car_Characteristics" cc
            JOIN "Characteristics" ch ON cc.characteristic_id = ch.characteristic_id
            WHERE cc.car_id = %s
        """, (car_id,), fetch="all")

        if chars is not None and not chars.empty:
            st.table(chars)
        else:
            st.info("Характеристики не вказані.")

    with c2:
        st.subheader("🛠️ Управління / Контакти")
        st.success(f"Обрано: **{curr_ann['brand']} {curr_ann['model']}**")

        is_owner = curr_ann['seller_user_id'] == st.session_state['user_id']
        is_staff = user_role in ['manager', 'admin']

        if is_owner or is_staff:
            actions = ["Редагувати ціну/опис", "Архівувати (Зняти з продажу)"]
            if is_staff:
                actions.append("🛠️ Редагувати Характеристики (Модерація)")

            action = st.radio("Дія:", actions, key=f"act_{sel_ann_id}")

            # 1. UPDATE
            if action == "Редагувати ціну/опис":
                with st.form(f"edit_{sel_ann_id}"):
                    np = st.number_input("Ціна:", value=float(curr_ann['price']))
                    nd = st.text_area("Опис:", value=curr_ann['description'])
                    if st.form_submit_button("Зберегти"):
                        run_query('UPDATE "Sale_Announcements" SET price=%s, description=%s WHERE announcement_id=%s',
                                  (np, nd, int(sel_ann_id)), commit=True)
                        log_action(st.session_state['user_id'], "UPDATE", "Sale_Announcements", int(sel_ann_id),
                                   f"Change Price: {np}")
                        st.cache_data.clear()
                        st.success("Оновлено!")
                        time.sleep(1)
                        st.rerun()

            # 2. ARCHIVE
            elif action == "Архівувати (Зняти з продажу)":
                if st.button("Підтвердити архівування", key=f"arch_{sel_ann_id}"):
                    run_query("UPDATE \"Sale_Announcements\" SET status='inactive' WHERE announcement_id=%s",
                              (int(sel_ann_id),), commit=True)
                    log_action(st.session_state['user_id'], "ARCHIVE", "Sale_Announcements", int(sel_ann_id),
                               "Archived")
                    st.cache_data.clear()
                    st.success("В архіві!")
                    time.sleep(1)
                    st.rerun()

            # 3. MODERATE
            elif action == "🛠️ Редагувати Характеристики (Модерація)":
                curr_chars_q = run_query('SELECT characteristic_id, value FROM "Car_Characteristics" WHERE car_id=%s',
                                         (car_id,), fetch="all")
                curr_dict = dict(
                    zip(curr_chars_q['characteristic_id'], curr_chars_q['value'])) if curr_chars_q is not None else {}

                with st.form(f"mod_{sel_ann_id}"):
                    new_vals = {}
                    if chars_ref_df is not None:
                        for _, row in chars_ref_df.iterrows():
                            cid, cname = row['characteristic_id'], row['name']
                            val = st.text_input(cname, value=curr_dict.get(cid, ""))
                            new_vals[cid] = val

                    if st.form_submit_button("Зберегти характеристики"):
                        try:
                            with get_db_connection() as conn:
                                with conn.cursor() as cur:
                                    for cid, val in new_vals.items():
                                        if val:
                                            cur.execute("""INSERT INTO "Car_Characteristics" (car_id, characteristic_id, value) VALUES (%s, %s, %s) 
                                                           ON CONFLICT (car_id, characteristic_id) DO UPDATE SET value=EXCLUDED.value""",
                                                        (car_id, cid, val))
                                        elif cid in curr_dict:
                                            cur.execute(
                                                'DELETE FROM "Car_Characteristics" WHERE car_id=%s AND characteristic_id=%s',
                                                (car_id, cid))
                                    conn.commit()
                            log_action(st.session_state['user_id'], "MODERATE", "Car_Characteristics", int(car_id),
                                       "Updated specs")
                            st.cache_data.clear()
                            st.success("Збережено!")
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

        else:
            owner_email = curr_ann['owner_email']
            owner_phone = curr_ann['owner_phone'] if curr_ann['owner_phone'] else "Не вказано"
            st.info("Контакти продавця:")
            st.markdown(f"📧 <a href='mailto:{owner_email}'>{owner_email}</a>", unsafe_allow_html=True)
            st.markdown(f"📞 <a href='tel:{owner_phone}'>{owner_phone}</a>", unsafe_allow_html=True)

else:
    st.info("👈 Оберіть автомобіль у таблиці вище.")