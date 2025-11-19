import streamlit as st
from db_utils import run_query
import datetime
import pandas as pd
import plotly.express as px  # <--- НОВА БІБЛІОТЕКА ДЛЯ КРАСИВИХ ГРАФІКІВ

st.set_page_config(page_title="Аналітика", layout="wide")
st.title("📊 Комплексна аналітика бізнесу")

# --- КОНСТАНТИ ---
COMMISSION_RATE = 0.05
COMPANY_EMAIL = 'company@marketplace.com'

# --- САЙДБАР ---
st.sidebar.header("⚙️ Налаштування звіту")
today = datetime.date.today()
year_ago = today - datetime.timedelta(days=365)
date_range = st.sidebar.date_input(
    "Період аналізу:", value=(year_ago, today),
    min_value=year_ago - datetime.timedelta(days=700), max_value=today
)

if len(date_range) != 2:
    st.info("Будь ласка, оберіть початкову та кінцеву дату.")
    st.stop()

start_date, end_date = date_range

# --- ВКЛАДКИ (TABS) ---
tab1, tab2, tab3 = st.tabs(["💰 Фінанси & Прибуток", "🚗 Популярність Авто", "👥 Ефективність Менеджерів"])

# ========================================================
# 1. ФІНАНСОВА АНАЛІТИКА (Оновлена)
# ========================================================
with tab1:
    st.header("💰 Фінансові показники")

    # Ми змінили аліаси (назви колонок) у SQL запиті
    finance_query = f"""
        WITH DealDetails AS (
            SELECT
                d.deal_id, d.final_price, d.deal_date, sa.car_id,
                (CASE WHEN u.email = '{COMPANY_EMAIL}' THEN true ELSE false END) AS is_company_deal
            FROM public."Deals" d
            JOIN public."Sale_Announcements" sa ON d.announcement_id = sa.announcement_id
            JOIN public."Users" u ON sa.seller_user_id = u.user_id
            WHERE d.deal_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        LatestBuybackCosts AS (
            SELECT car_id, COALESCE(offer_price, desired_price) AS cost_price
            FROM (
                SELECT car_id, offer_price, desired_price,
                       ROW_NUMBER() OVER(PARTITION BY car_id ORDER BY request_date DESC) as rn
                FROM public."Buyback_Requests" 
                WHERE status = 'completed'
            ) AS RankedCosts
            WHERE rn = 1
        )
        SELECT
            date_trunc('month', dd.deal_date)::date AS sales_month,

            -- ПЕРЕЙМЕНУВАЛИ total_profit -> resale_margin
            SUM(COALESCE(CASE WHEN dd.is_company_deal THEN dd.final_price - lbc.cost_price ELSE 0 END, 0))::bigint AS resale_margin,

            -- ПЕРЕЙМЕНУВАЛИ total_commission -> commission_revenue
            SUM(CASE WHEN NOT dd.is_company_deal THEN dd.final_price * {COMMISSION_RATE} ELSE 0 END)::bigint AS commission_revenue,

            COUNT(dd.deal_id) AS total_deals,
            SUM(dd.final_price)::bigint AS total_turnover
        FROM DealDetails dd
        LEFT JOIN LatestBuybackCosts lbc ON dd.car_id = lbc.car_id
        GROUP BY sales_month
        ORDER BY sales_month ASC;
    """
    df_fin = run_query(finance_query, fetch="all")

    if df_fin is not None and not df_fin.empty:
        # Розрахунок загального чистого доходу компанії
        df_fin['Net Income'] = df_fin['resale_margin'] + df_fin['commission_revenue']

        # Розрахунок Середнього чека (Оборот / Кількість)
        total_turnover = df_fin['total_turnover'].sum()
        total_deals_count = df_fin['total_deals'].sum()
        avg_check = total_turnover / total_deals_count if total_deals_count > 0 else 0

        # --- МЕТРИКИ (KPI) ---
        m1, m2, m3, m4 = st.columns(4)

        with m1:
            st.metric(
                "Маржа з перепродажу",
                f"${df_fin['resale_margin'].sum():,.0f}",
                help="Чистий прибуток від авто, викуплених компанією (Ціна продажу - Ціна викупу)."
            )
        with m2:
            st.metric(
                "Комісійний дохід",
                f"${df_fin['commission_revenue'].sum():,.0f}",
                help="Дохід від угод між звичайними користувачами (5% від ціни)."
            )
        with m3:
            st.metric(
                "Загальний чистий дохід",
                f"${df_fin['Net Income'].sum():,.0f}",
                delta="Сума маржі та комісій"
            )
        with m4:
            st.metric(
                "Середній чек авто",
                f"${avg_check:,.0f}",
                help="Середня вартість автомобіля, проданого на платформі (Оборот / Кількість угод)."
            )

        st.divider()

        # --- ГРАФІК 1: СТРУКТУРА ДОХОДУ ---
        # Перейменовуємо колонки для легенди графіка
        df_chart = df_fin.rename(columns={
            'resale_margin': 'Маржа (Trade-in)',
            'commission_revenue': 'Комісія (P2P)'
        })

        fig_income = px.bar(
            df_chart,
            x='sales_month',
            y=['Маржа (Trade-in)', 'Комісія (P2P)'],
            title="Структура чистого доходу",
            labels={'value': 'Сума ($)', 'sales_month': 'Місяць', 'variable': 'Джерело прибутку'},
            barmode='group',
            color_discrete_map={'Маржа (Trade-in)': '#00CC96', 'Комісія (P2P)': '#636EFA'}
        )
        st.plotly_chart(fig_income, use_container_width=True)

        # --- ГРАФІК 2: ОБОРОТ ТА УГОДИ ---
        fig_deals = px.line(
            df_fin, x='sales_month', y='total_deals', markers=True,
            title="Кількість укладених угод",
            labels={'total_deals': 'Угод (шт.)', 'sales_month': 'Місяць'},
            line_shape='spline', color_discrete_sequence=['#EF553B']
        )
        st.plotly_chart(fig_deals, use_container_width=True)

        # Таблиця для детального перегляду
        with st.expander("Переглянути детальні цифри в таблиці"):
            st.dataframe(df_fin, use_container_width=True)

    else:
        st.warning("Немає фінансових даних за цей період.")

# ========================================================
# 2. АНАЛІТИКА ПО БРЕНДАХ (НОВЕ)
# ========================================================
with tab2:
    st.header("Топ продажів за марками")

    brand_query = f"""
        SELECT 
            b.name AS brand_name,
            COUNT(d.deal_id) AS deals_count,
            SUM(d.final_price) AS total_volume
        FROM public."Deals" d
        JOIN public."Sale_Announcements" sa ON d.announcement_id = sa.announcement_id
        JOIN public."Cars" c ON sa.car_id = c.car_id
        JOIN public."Models" m ON c.model_id = m.model_id
        JOIN public."Brands" b ON m.brand_id = b.brand_id
        WHERE d.deal_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY b.name
        ORDER BY deals_count DESC
        LIMIT 10;
    """
    df_brands = run_query(brand_query, fetch="all")

    if df_brands is not None and not df_brands.empty:
        c1, c2 = st.columns([1, 2])

        with c1:
            st.write("##### Топ-10 Брендів за кількістю продажів")
            st.dataframe(df_brands[['brand_name', 'deals_count', 'total_volume']], hide_index=True)

        with c2:
            # Кругова діаграма (Pie Chart)
            fig_pie = px.pie(
                df_brands, values='deals_count', names='brand_name',
                title="Частка брендів у продажах",
                hole=0.4
            )
            st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("Недостатньо даних для аналізу брендів.")

# ========================================================
# 3. ЕФЕКТИВНІСТЬ МЕНЕДЖЕРІВ (НОВЕ)
# ========================================================
with tab3:
    st.header("KPI Менеджерів (Викуп авто)")
    st.caption("Хто з менеджерів найуспішніше закриває заявки на Trade-in?")

    manager_query = f"""
        SELECT 
            e.first_name || ' ' || e.last_name AS manager_name,
            COUNT(br.request_id) AS completed_buybacks,
            AVG(br.offer_price)::numeric(10,2) AS avg_buy_price
        FROM public."Buyback_Requests" br
        JOIN public."Employees" e ON br.manager_id = e.employee_id
        WHERE br.status = 'completed'
        -- Можна додати фільтр по даті request_date, якщо потрібно
        GROUP BY manager_name
        ORDER BY completed_buybacks DESC;
    """
    df_managers = run_query(manager_query, fetch="all")

    if df_managers is not None and not df_managers.empty:
        # Горизонтальний бар-чарт для лідерборду
        fig_mgr = px.bar(
            df_managers, x='completed_buybacks', y='manager_name', orientation='h',
            title="Рейтинг менеджерів (кількість викуплених авто)",
            text='completed_buybacks',
            color='completed_buybacks', color_continuous_scale='Viridis'
        )
        st.plotly_chart(fig_mgr, use_container_width=True)

        st.write("Детальна статистика:")
        st.dataframe(df_managers, use_container_width=True)
    else:
        st.info("Немає даних про завершені заявки з призначеними менеджерами.")