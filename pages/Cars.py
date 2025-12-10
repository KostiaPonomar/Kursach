import streamlit as st
from db_utils import run_query, log_action, get_db_connection
from navigation import make_sidebar
import pandas as pd
import uuid
import time

st.set_page_config(page_title="База Автомобілів", layout="wide")

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

st.title("🚘 База автомобілів")


# Завантажуємо довідник характеристик
@st.cache_data
def load_dictionaries():
    return run_query('SELECT characteristic_id, name FROM public."Characteristics" ORDER BY name;', fetch="all")


characteristics_df = load_dictionaries()


# --- ФУНКЦІЇ ЗАВАНТАЖЕННЯ ---
@st.cache_data
def load_verified_data():
    cars_query = """
    SELECT 
        c.car_id, b.name AS brand, m.name AS model, u.email AS owner_email,
        c.vin_code, c.year, c.mileage
    FROM public."Cars" c
    LEFT JOIN public."Models" m ON c.model_id = m.model_id
    LEFT JOIN public."Brands" b ON m.brand_id = b.brand_id
    LEFT JOIN public."Users" u ON c.owner_id = u.user_id
    WHERE c.verification_status = 'verified'
    ORDER BY c.car_id DESC;
    """
    cars = run_query(cars_query, fetch="all")
    users = run_query('SELECT user_id, email FROM public."Users" ORDER BY email;', fetch="all")
    active_ads_df = run_query("SELECT car_id FROM \"Sale_Announcements\" WHERE status = 'active'", fetch="all")
    active_ads_ids = active_ads_df['car_id'].tolist() if active_ads_df is not None else []
    return cars, users, active_ads_ids


@st.cache_data
def load_moderation_data():
    mod_query = """
    SELECT 
        c.car_id, b.name AS brand, m.name AS model, 
        c.year, c.vin_code, c.mileage, 
        c.verification_status, c.rejection_reason, 
        u.email as owner
    FROM "Cars" c
    JOIN "Models" m ON c.model_id = m.model_id
    JOIN "Brands" b ON m.brand_id = b.brand_id
    JOIN "Users" u ON c.owner_id = u.user_id
    WHERE c.verification_status IN ('pending', 'rejected')
    ORDER BY c.car_id ASC
    """
    return run_query(mod_query, fetch="all")


# --- НАВІГАЦІЯ (ЗАМІСТЬ TABS) ---
# Використовуємо radio, бо воно краще тримає стан при перезавантаженні
view_mode = st.radio(
    "Оберіть режим:",
    ["🗂️ Загальна база (Verified)", "🛡️ Модерація (Pending & Rejected)"],
    horizontal=True
)

st.divider()

# ==============================================================================
# РЕЖИМ 1: ЗАГАЛЬНА БАЗА
# ==============================================================================
if view_mode == "🗂️ Загальна база (Verified)":

    cars_df, users_df, active_ads_ids = load_verified_data()

    if cars_df is None:
        st.error("Помилка завантаження даних.")
        st.stop()

    # --- САЙДБАР: ФІЛЬТРИ ---
    st.sidebar.header("Фільтри бази")

    filter_company = st.sidebar.checkbox("🏢 Тільки авто компанії", key="filter_comp")
    filter_no_ads = st.sidebar.checkbox("📢 Тільки БЕЗ оголошень", key="filter_no_ads")
    search_text = st.sidebar.text_input("🔍 Пошук (VIN / Email):", key="search_text")

    all_brands = sorted(list(cars_df['brand'].unique())) if cars_df is not None and not cars_df.empty else []
    brand_filter = st.sidebar.selectbox("Марка:", options=["Всі"] + all_brands, key="brand_filter")

    filtered_models = []
    if brand_filter != "Всі" and cars_df is not None:
        filtered_models = sorted(cars_df[cars_df['brand'] == brand_filter]['model'].unique())
    else:
        filtered_models = sorted(cars_df['model'].unique()) if cars_df is not None and not cars_df.empty else []
    model_filter = st.sidebar.selectbox("Модель:", options=["Всі"] + filtered_models, key="model_filter")

    filtered_df = cars_df.copy() if cars_df is not None else pd.DataFrame()

    if not filtered_df.empty:
        if filter_company: filtered_df = filtered_df[filtered_df['owner_email'] == 'company@marketplace.com']
        if filter_no_ads: filtered_df = filtered_df[~filtered_df['car_id'].isin(active_ads_ids)]
        if search_text:
            mask = (filtered_df['vin_code'].str.contains(search_text, case=False) |
                    filtered_df['owner_email'].str.contains(search_text, case=False))
            filtered_df = filtered_df[mask]
        if brand_filter != "Всі": filtered_df = filtered_df[filtered_df['brand'] == brand_filter]
        if model_filter != "Всі": filtered_df = filtered_df[filtered_df['model'] == model_filter]

    if filtered_df.empty:
        st.info("Записів не знайдено.")
    else:
        st.dataframe(filtered_df, use_container_width=True)
        st.caption(f"Автомобілів у списку: {len(filtered_df)}")

    st.divider()

    # ХАРАКТЕРИСТИКИ
    st.subheader("⚙️ Редагування характеристик")
    if not filtered_df.empty:
        sel_car_id = st.selectbox("Оберіть авто:", options=filtered_df['car_id'], key="sel_car_char")

        curr_chars = run_query('SELECT characteristic_id, value FROM "Car_Characteristics" WHERE car_id=%s',
                               (sel_car_id,), fetch="all")
        curr_dict = dict(zip(curr_chars['characteristic_id'], curr_chars['value'])) if curr_chars is not None else {}

        with st.form("chars_form_tab1"):
            new_vals = {}
            if characteristics_df is not None:
                cols = st.columns(3)
                for idx, row in characteristics_df.iterrows():
                    c_id, c_name = row['characteristic_id'], row['name']
                    with cols[idx % 3]:
                        val = st.text_input(c_name, value=curr_dict.get(c_id, ""))
                        new_vals[c_id] = val

            if st.form_submit_button("Зберегти характеристики"):
                try:
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            for cid, val in new_vals.items():
                                if val:
                                    cur.execute(
                                        """INSERT INTO "Car_Characteristics" (car_id, characteristic_id, value) VALUES (%s, %s, %s) ON CONFLICT (car_id, characteristic_id) DO UPDATE SET value = EXCLUDED.value;""",
                                        (sel_car_id, cid, val))
                                elif cid in curr_dict:
                                    cur.execute(
                                        'DELETE FROM "Car_Characteristics" WHERE car_id=%s AND characteristic_id=%s',
                                        (sel_car_id, cid))
                            conn.commit()
                    log_action(st.session_state['user_id'], "MODERATE", "Car_Characteristics", int(sel_car_id),
                               "Зміна характеристик")
                    st.success("Характеристики оновлено!")
                except Exception as e:
                    st.error(f"Помилка: {e}")

    st.divider()
    st.subheader("🛠️ Управління базою")
    operation = st.selectbox("Дія:", ["Додати авто (Менеджером)", "Створити оголошення", "Видалити авто"])

    if operation == "Додати авто (Менеджером)":
        st.write("Створене авто одразу отримає статус 'Verified'.")
        with st.form("add_car_mgr"):
            c1, c2 = st.columns(2)
            brand = c1.text_input("Марка")
            model = c2.text_input("Модель")
            owner = st.selectbox("Власник:", options=users_df['user_id'],
                                 format_func=lambda x: users_df.loc[users_df['user_id'] == x, 'email'].iloc[0])
            c3, c4, c5 = st.columns(3)
            vin = c3.text_input("VIN", value=uuid.uuid4().hex[:17].upper())
            year = c4.number_input("Рік", 1900, 2025, 2020)
            mileage = c5.number_input("Пробіг", 0, 1000000, 0)

            if st.form_submit_button("Додати"):
                try:
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute('SELECT brand_id FROM "Brands" WHERE name=%s', (brand,))
                            res = cur.fetchone()
                            bid = res[0] if res else cur.execute(
                                'INSERT INTO "Brands" (name) VALUES (%s) RETURNING brand_id', (brand,)) or \
                                                     cur.fetchone()[0]
                            cur.execute('SELECT model_id FROM "Models" WHERE name=%s AND brand_id=%s', (model, bid))
                            res = cur.fetchone()
                            mid = res[0] if res else cur.execute(
                                'INSERT INTO "Models" (brand_id, name) VALUES (%s, %s) RETURNING model_id',
                                (bid, model)) or cur.fetchone()[0]
                            cur.execute(
                                """INSERT INTO "Cars" (model_id, owner_id, vin_code, year, mileage, verification_status) VALUES (%s, %s, %s, %s, %s, 'verified') RETURNING car_id;""",
                                (mid, owner, vin, year, mileage))
                            new_id = cur.fetchone()[0]
                        conn.commit()
                    log_action(st.session_state['user_id'], "INSERT", "Cars", new_id,
                               f"Менеджер додав авто {brand} {model}")
                    st.cache_data.clear();
                    st.success("Автомобіль додано!");
                    time.sleep(1);
                    st.rerun()
                except Exception as e:
                    st.error(f"Помилка: {e}")

    elif operation == "Створити оголошення":
        car_id_ann = st.selectbox("Оберіть авто для продажу:", options=filtered_df['car_id'])
        if car_id_ann:
            car_info = filtered_df[filtered_df['car_id'] == car_id_ann].iloc[0]
            if car_info['owner_email'] != 'company@marketplace.com':
                st.error("⛔ Менеджер може створювати оголошення ТІЛЬКИ для авто компанії.")
            else:
                active_req = run_query(
                    'SELECT request_id FROM "Buyback_Requests" WHERE car_id=%s AND status NOT IN (\'completed\', \'rejected\')',
                    (car_id_ann,), fetch="one")
                active_ann = run_query(
                    'SELECT announcement_id FROM "Sale_Announcements" WHERE car_id=%s AND status=\'active\'',
                    (car_id_ann,), fetch="one")

                if active_req:
                    st.error(f"⛔ Авто в процесі викупу (ID {active_req[0]}).")
                elif active_ann:
                    st.error(f"⛔ Активне оголошення вже існує (ID {active_ann[0]}).")
                else:
                    with st.form("create_ann_mgr"):
                        title = st.text_input("Заголовок",
                                              value=f"{car_info['brand']} {car_info['model']} {car_info['year']}")
                        desc = st.text_area("Опис", value="Офіційне авто. Перевірено.")
                        price = st.number_input("Ціна ($)", min_value=0.0, step=100.0)
                        if st.form_submit_button("Опублікувати"):
                            try:
                                owner_id = \
                                run_query('SELECT owner_id FROM "Cars" WHERE car_id=%s', (car_id_ann,), fetch="one")[0]
                                query = """INSERT INTO "Sale_Announcements" (car_id, seller_user_id, title, description, price, status, creation_date) VALUES (%s, %s, %s, %s, %s, 'active', CURRENT_TIMESTAMP) ON CONFLICT (car_id) DO UPDATE SET title=EXCLUDED.title, description=EXCLUDED.description, price=EXCLUDED.price, status='active', seller_user_id=EXCLUDED.seller_user_id;"""
                                run_query(query, (car_id_ann, owner_id, title, desc, price), commit=True)
                                log_action(st.session_state['user_id'], "INSERT/UPDATE", "Sale_Announcements", None,
                                           f"Оголошення компанії {car_id_ann}")
                                st.cache_data.clear();
                                st.success("Опубліковано!");
                                time.sleep(1);
                                st.rerun()
                            except Exception as e:
                                st.error(f"Помилка: {e}")

    elif operation == "Видалити авто":
        del_cid = st.selectbox("Авто для видалення:", options=filtered_df['car_id'])
        if st.button("🗑️ Видалити назавжди"):
            try:
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute('DELETE FROM "Sale_Announcements" WHERE car_id=%s', (del_cid,))
                        cur.execute('DELETE FROM "Buyback_Requests" WHERE car_id=%s', (del_cid,))
                        cur.execute('DELETE FROM "Cars" WHERE car_id=%s', (del_cid,))
                    conn.commit()
                log_action(st.session_state['user_id'], "DELETE", "Cars", int(del_cid), "Повне видалення")
                st.cache_data.clear();
                st.success("Видалено.");
                time.sleep(1);
                st.rerun()
            except Exception as e:
                st.error(f"Помилка: {e}")

# ==============================================================================
# РЕЖИМ 2: МОДЕРАЦІЯ
# ==============================================================================
elif view_mode == "🛡️ Модерація (Pending & Rejected)":
    st.subheader("🛡️ Перевірка та редагування заявок")

    mod_df = load_moderation_data()

    if mod_df is not None and not mod_df.empty:
        def highlight_mod(val):
            color = '#fff3cd' if val == 'pending' else '#f8d7da'
            return f'background-color: {color}; color: black'


        st.info("👇 Натисніть на рядок, щоб перевірити деталі.")

        event = st.dataframe(
            mod_df.style.map(highlight_mod, subset=['verification_status']),
            use_container_width=True,
            on_select="rerun",
            selection_mode="single-row",
            hide_index=True,
            key="mod_table"
        )

        if len(event.selection.rows) > 0:
            sel_idx = event.selection.rows[0]
            sel_row = mod_df.iloc[sel_idx]
            mod_car_id = int(sel_row['car_id'])
            status = sel_row['verification_status']

            st.divider()
            st.write(f"### 📝 Редагування заявки #{mod_car_id}")
            st.write(f"**Власник:** {sel_row['owner']}")

            curr_chars = run_query('SELECT characteristic_id, value FROM "Car_Characteristics" WHERE car_id=%s',
                                   (mod_car_id,), fetch="all")
            curr_dict = dict(
                zip(curr_chars['characteristic_id'], curr_chars['value'])) if curr_chars is not None else {}

            with st.form(f"mod_form_{mod_car_id}"):
                c1, c2 = st.columns(2)
                new_brand = c1.text_input("Марка", value=sel_row['brand'])
                new_model = c2.text_input("Модель", value=sel_row['model'])

                c3, c4, c5 = st.columns(3)
                new_vin = c3.text_input("VIN", value=sel_row['vin_code'])
                new_year = c4.number_input("Рік", value=int(sel_row['year']))
                new_mileage = c5.number_input("Пробіг", value=int(sel_row['mileage']))

                st.write("**Характеристики (редагування):**")
                new_char_vals = {}
                if characteristics_df is not None:
                    cols = st.columns(3)
                    for idx, row in characteristics_df.iterrows():
                        cid, cname = row['characteristic_id'], row['name']
                        with cols[idx % 3]:
                            val = st.text_input(cname, value=curr_dict.get(cid, ""))
                            new_char_vals[cid] = val

                st.markdown("---")
                col_ok, col_bad = st.columns([3, 1])

                approve = col_ok.form_submit_button("💾 Зберегти та Підтвердити (Verify)")

                if approve:
                    try:
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                # 1. Бренд
                                cur.execute('SELECT brand_id FROM "Brands" WHERE name=%s', (new_brand,))
                                res_b = cur.fetchone()
                                if res_b:
                                    bid = res_b[0]
                                else:
                                    cur.execute('INSERT INTO "Brands" (name) VALUES (%s) RETURNING brand_id',
                                                (new_brand,)); bid = cur.fetchone()[0]

                                # 2. Модель
                                cur.execute('SELECT model_id FROM "Models" WHERE name=%s AND brand_id=%s',
                                            (new_model, bid))
                                res_m = cur.fetchone()
                                if res_m:
                                    mid = res_m[0]
                                else:
                                    cur.execute(
                                        'INSERT INTO "Models" (brand_id, name) VALUES (%s, %s) RETURNING model_id',
                                        (bid, new_model)); mid = cur.fetchone()[0]

                                # 3. Оновлення
                                cur.execute(
                                    """UPDATE "Cars" SET model_id=%s, vin_code=%s, year=%s, mileage=%s, verification_status='verified', rejection_reason=NULL WHERE car_id=%s""",
                                    (mid, new_vin, new_year, new_mileage, mod_car_id))
                                cur.execute('DELETE FROM "Car_Characteristics" WHERE car_id=%s', (mod_car_id,))
                                for cid, val in new_char_vals.items():
                                    if val.strip():
                                        cur.execute('INSERT INTO "Car_Characteristics" VALUES (%s, %s, %s)',
                                                    (mod_car_id, cid, val.strip()))
                            conn.commit()

                        log_action(st.session_state['user_id'], "MODERATE", "Cars", mod_car_id, "Verified")
                        st.cache_data.clear()  # ЧИСТИМО КЕШ
                        st.success("Дані оновлено, авто підтверджено!")
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Помилка при збереженні: {e}")

            with st.expander("❌ Відхилити заявку"):
                with st.form("reject_form"):
                    reason = st.text_area("Причина:", placeholder="Некоректні дані")
                    if st.form_submit_button("Відхилити"):
                        if not reason:
                            st.error("Вкажіть причину!")
                        else:
                            run_query(
                                "UPDATE \"Cars\" SET verification_status='rejected', rejection_reason=%s WHERE car_id=%s",
                                (reason, mod_car_id), commit=True)
                            log_action(st.session_state['user_id'], "MODERATE", "Cars", mod_car_id,
                                       f"REJECTED: {reason}")
                            st.cache_data.clear()  # ЧИСТИМО КЕШ
                            st.warning("Заявку відхилено.")
                            time.sleep(1)
                            st.rerun()

            if status == 'rejected':
                st.markdown("---")
                if st.button("🗑️ Видалити це сміття з бази", key=f"del_{mod_car_id}"):
                    try:
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute('DELETE FROM "Car_Characteristics" WHERE car_id=%s', (mod_car_id,))
                                cur.execute('DELETE FROM "Cars" WHERE car_id=%s', (mod_car_id,))
                            conn.commit()
                        log_action(st.session_state['user_id'], "DELETE", "Cars", mod_car_id, "Cleaned up")
                        st.cache_data.clear()  # ЧИСТИМО КЕШ
                        st.success("Видалено.");
                        time.sleep(1);
                        st.rerun()
                    except Exception as e:
                        st.error(f"Помилка: {e}")
    else:
        st.success("Нових заявок немає.")