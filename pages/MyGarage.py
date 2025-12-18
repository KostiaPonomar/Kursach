import streamlit as st
from db_utils import run_query, log_action, get_db_connection
from navigation import make_sidebar
import pandas as pd
import time

st.set_page_config(page_title="Мій Гараж", layout="wide")

# --- 🔒 ЗАХИСТ ДОСТУПУ ---
if 'user_id' not in st.session_state or st.session_state['user_id'] is None:
    st.warning("Будь ласка, увійдіть в систему.")
    st.switch_page("main.py")
    st.stop()

make_sidebar()
CURRENT_USER = st.session_state['user_id']

st.title(f"🚗 Гараж користувача {st.session_state['username']}")


# --- ЗАВАНТАЖЕННЯ ДАНИХ ---
@st.cache_data
def load_my_data(uid):
    # 1. Мої авто
    cars_query = """
    SELECT 
        c.car_id, 
        b.name AS brand, m.name AS model, c.year,
        b.name || ' ' || m.name || ' (' || c.year || ')' AS title, 
        c.vin_code, c.mileage,
        c.verification_status, c.rejection_reason
    FROM public."Cars" c
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    WHERE c.owner_id = %s
    ORDER BY c.car_id DESC;
    """
    my_cars = run_query(cars_query, (uid,), fetch="all")

    # 2. Заявки Trade-in
    requests_query = """
    SELECT br.request_id, br.car_id, br.status, br.offer_price, br.desired_price,
           b.name || ' ' || m.name AS car_name
    FROM public."Buyback_Requests" br
    JOIN public."Cars" c ON br.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    WHERE br.user_id = %s AND br.status NOT IN ('completed', 'rejected');
    """
    my_requests = run_query(requests_query, (uid,), fetch="all")

    # 3. Мої оголошення
    ads_query = """
    SELECT 
        sa.announcement_id, 
        sa.car_id, 
        sa.price, 
        sa.status, 
        b.name || ' ' || m.name || ' (' || c.year || ')' AS car_name
    FROM public."Sale_Announcements" sa
    JOIN public."Cars" c ON sa.car_id = c.car_id
    JOIN public."Models" m ON c.model_id = m.model_id
    JOIN public."Brands" b ON m.brand_id = b.brand_id
    WHERE sa.seller_user_id = %s AND sa.status = 'active';
    """
    my_ads = run_query(ads_query, (uid,), fetch="all")

    chars_ref = run_query('SELECT characteristic_id, name FROM public."Characteristics" ORDER BY name;', fetch="all")

    return my_cars, my_requests, my_ads, chars_ref


cars_df, req_df, ads_df, chars_df = load_my_data(CURRENT_USER)

# ==========================================
# 1. ДОДАВАННЯ НОВОГО АВТО
# ==========================================
st.subheader("➕ Заявка на реєстрацію авто")
with st.expander("Натисніть, щоб додати авто"):
    with st.form("add_my_new_car"):
        c1, c2 = st.columns(2)
        brand = c1.text_input("Марка (напр. Toyota)")
        model = c2.text_input("Модель (напр. Camry)")
        c3, c4, c5 = st.columns(3)
        vin = c3.text_input("VIN (17 симв.)")
        year = c4.number_input("Рік", 1900, 2025, 2018)
        mileage = c5.number_input("Пробіг", 0, 1000000, 50000)

        st.write("Характеристики:")
        char_inputs = {}
        if chars_df is not None:
            cols = st.columns(3)
            for idx, row in chars_df.iterrows():
                with cols[idx % 3]:
                    val = st.text_input(row['name'], key=f"add_{row['characteristic_id']}")
                    char_inputs[row['characteristic_id']] = val

        if st.form_submit_button("Надіслати на перевірку"):
            if not all([brand, model, vin]) or len(vin) != 17:
                st.error("Некоректні дані (VIN має бути 17 символів).")
            else:
                try:
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute('SELECT brand_id FROM "Brands" WHERE name=%s', (brand,))
                            res = cur.fetchone()
                            b_id = res[0] if res else cur.execute(
                                'INSERT INTO "Brands" (name) VALUES (%s) RETURNING brand_id', (brand,)) or \
                                                      cur.fetchone()[0]
                            cur.execute('SELECT model_id FROM "Models" WHERE name=%s AND brand_id=%s', (model, b_id))
                            res = cur.fetchone()
                            m_id = res[0] if res else cur.execute(
                                'INSERT INTO "Models" (brand_id, name) VALUES (%s, %s) RETURNING model_id',
                                (b_id, model)) or cur.fetchone()[0]
                            cur.execute(
                                """INSERT INTO "Cars" (model_id, owner_id, vin_code, year, mileage, verification_status) VALUES (%s, %s, %s, %s, %s, 'pending') RETURNING car_id;""",
                                (m_id, CURRENT_USER, vin, year, mileage))
                            new_car_id = cur.fetchone()[0]
                            for cid, cval in char_inputs.items():
                                if cval.strip(): cur.execute('INSERT INTO "Car_Characteristics" VALUES (%s, %s, %s)',
                                                             (new_car_id, cid, cval.strip()))
                        conn.commit()
                    log_action(CURRENT_USER, "INSERT", "Cars", new_car_id, f"Заявка на реєстрацію авто {brand} {model}")
                    st.success("Заявку відправлено! Очікуйте підтвердження менеджера.")
                    st.cache_data.clear()
                    time.sleep(2)
                    st.rerun()
                except Exception as e:
                    st.error(f"Помилка: {e}")

st.divider()

# ==========================================
# 2. СПИСОК АВТО
# ==========================================
st.subheader("🚘 Мої автомобілі")

if cars_df is not None and not cars_df.empty:
    def highlight_status(val):
        color = '#d4edda' if val == 'verified' else '#fff3cd' if val == 'pending' else '#f8d7da'
        return f'background-color: {color}; color: black'


    st.dataframe(cars_df.style.map(highlight_status, subset=['verification_status']), use_container_width=True)

    st.write("⚡ **Дії з вибраним авто:**")


    # --- ВИПРАВЛЕННЯ: Унікальні назви для списку ---
    def fmt_car(cid):
        row = cars_df[cars_df['car_id'] == cid].iloc[0]
        st_icon = {"verified": "✅", "pending": "⏳", "rejected": "❌"}
        # Додаємо ID, щоб ідентифікувати однакові моделі
        return f"{st_icon.get(row['verification_status'], '')} {row['title']} (ID: {cid})"


    sel_car = st.selectbox("Оберіть авто зі списку:", options=cars_df['car_id'], format_func=fmt_car)

    # --- ПРЯМА ПЕРЕВІРКА В БД ---
    p2p_check = run_query(
        'SELECT announcement_id FROM "Sale_Announcements" WHERE car_id=%s AND status=\'active\'',
        (int(sel_car),), fetch="one"
    )
    on_p2p = p2p_check is not None

    trade_check = run_query(
        'SELECT request_id FROM "Buyback_Requests" WHERE car_id=%s AND status NOT IN (\'completed\', \'rejected\')',
        (int(sel_car),), fetch="one"
    )
    on_tradein = trade_check is not None

    car_row = cars_df[cars_df['car_id'] == sel_car].iloc[0]
    status = car_row['verification_status']

    # --- ВІДОБРАЖЕННЯ СТАТУСУ ---
    if on_p2p:
        st.info(f"📢 Це авто (ID {sel_car}) зараз продається на сайті (P2P).")
    if on_tradein:
        st.info(f"🔄 Подано заявку на Trade-in для авто ID {sel_car}.")

    # --- ЛОГІКА ДІЙ ---
    if status == 'verified':
        c1, c2 = st.columns(2)

        # P2P
        with c1:
            with st.popover("📢 Продати на сайті (P2P)", disabled=on_tradein):
                if on_tradein:
                    st.error("Авто на етапі викупу.")
                else:
                    btn_text = "Оновити оголошення" if on_p2p else "Опублікувати"
                    st.write(btn_text)
                    p_price = st.number_input("Ціна продажу ($):", min_value=500.0, step=100.0, key=f"p2p_p_{sel_car}")
                    p_desc = st.text_area("Опис:", placeholder="Не бита...", key=f"p2p_d_{sel_car}")

                    if st.button(btn_text, key=f"p2p_btn_{sel_car}"):
                        try:
                            run_query("""
                                INSERT INTO "Sale_Announcements" (car_id, seller_user_id, title, description, price, status)
                                VALUES (%s, %s, %s, %s, %s, 'active')
                                ON CONFLICT (car_id) DO UPDATE SET price=EXCLUDED.price, description=EXCLUDED.description, status='active';
                            """, (sel_car, CURRENT_USER, car_row['title'], p_desc, p_price), commit=True)

                            log_action(CURRENT_USER, "INSERT", "Sale_Announcements", None, f"Оголошення: {sel_car}")
                            st.success("Готово!")
                            st.cache_data.clear()
                            time.sleep(1)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Помилка: {e}")

        # Trade-in
        with c2:
            with st.popover("🔄 Продати компанії (Trade-in)", disabled=(on_p2p or on_tradein)):
                if on_p2p:
                    st.error("Спочатку зніміть оголошення з продажу.")
                elif on_tradein:
                    st.error("Заявка вже активна.")
                else:
                    st.write("Подати заявку")
                    t_price = st.number_input("Бажана ціна ($):", min_value=500.0, step=100.0, key=f"tr_p_{sel_car}")
                    if st.button("Відправити заявку", key=f"tr_btn_{sel_car}"):
                        run_query(
                            'INSERT INTO "Buyback_Requests" (car_id, user_id, desired_price, status) VALUES (%s, %s, %s, \'new\')',
                            (sel_car, CURRENT_USER, t_price), commit=True)
                        log_action(CURRENT_USER, "INSERT", "Buyback_Requests", None, f"Trade-in: {sel_car}")
                        st.success("Відправлено!")
                        st.cache_data.clear()
                        time.sleep(1)
                        st.rerun()

    # --- REJECTED ---
    elif status == 'rejected':
        st.error(f"⛔ **Заявку відхилено!** Причина: {car_row['rejection_reason']}")
        with st.expander("✏️ Виправити дані та подати знову"):
            with st.form(f"fix_car_{sel_car}"):
                n_vin = st.text_input("VIN", value=car_row['vin_code'])
                n_mileage = st.number_input("Пробіг", value=car_row['mileage'])
                if st.form_submit_button("Відправити повторно"):
                    run_query("""
                        UPDATE "Cars" SET vin_code=%s, mileage=%s, verification_status='pending', rejection_reason=NULL 
                        WHERE car_id=%s
                    """, (n_vin, n_mileage, sel_car), commit=True)
                    log_action(CURRENT_USER, "UPDATE", "Cars", int(sel_car), "Resubmitted")
                    st.success("Відправлено!");
                    st.cache_data.clear();
                    time.sleep(1);
                    st.rerun()

    # --- PENDING ---
    elif status == 'pending':
        st.warning("⏳ Автомобіль знаходиться на перевірці.")
        if st.button("Скасувати заявку (Видалити)", key=f"del_pend_{sel_car}"):
            run_query('DELETE FROM "Cars" WHERE car_id=%s', (sel_car,), commit=True)
            st.success("Скасовано.");
            st.cache_data.clear();
            time.sleep(1);
            st.rerun()

else:
    st.info("У вас немає зареєстрованих автомобілів.")

st.divider()

# 3. TRADE-IN ЗАЯВКИ
st.subheader("📥 Статус заявок на викуп")
if req_df is not None and not req_df.empty:
    for _, row in req_df.iterrows():
        with st.expander(f"{row['car_name']} (Статус: {row['status'].upper()})"):
            st.write(f"Ціна: ${row['desired_price']}")
            if row['offer_price'] and row['status'] == 'offer_made':
                st.success(f"Пропозиція: ${row['offer_price']}")
                c1, c2 = st.columns(2)
                if c1.button("✅ Прийняти", key=f"y{row['request_id']}"):
                    run_query("UPDATE \"Buyback_Requests\" SET status='approved' WHERE request_id=%s",
                              (row['request_id'],), commit=True)
                    log_action(CURRENT_USER, "UPDATE", "Buyback_Requests", row['request_id'], "Accepted offer")
                    st.cache_data.clear();
                    st.rerun()
                if c2.button("❌ Відхилити", key=f"n{row['request_id']}"):
                    run_query("UPDATE \"Buyback_Requests\" SET status='rejected' WHERE request_id=%s",
                              (row['request_id'],), commit=True)
                    st.cache_data.clear();
                    st.rerun()
            else:
                st.info("В обробці.")
else:
    st.caption("Немає заявок.")

st.divider()

# 4. МОЇ ОГОЛОШЕННЯ
st.subheader("📢 Мої активні оголошення")
if ads_df is not None and not ads_df.empty:
    st.dataframe(ads_df[['car_name', 'price', 'status']], use_container_width=True)
else:
    st.caption("Немає оголошень.")