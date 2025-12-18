import streamlit as st
from db_utils import run_query, log_action
import datetime
import plotly.express as px
import pandas as pd
from navigation import make_sidebar

st.set_page_config(page_title="Аналітика", layout="wide")

# --- 🔒 ЗАХИСТ ДОСТУПУ (RBAC) ---
if 'user_id' not in st.session_state or st.session_state['user_id'] is None:
    st.warning("Будь ласка, увійдіть в систему.")
    st.switch_page("main.py")
    st.stop()

if st.session_state['role'] != 'admin':
    st.error("⛔ Немає доступу! Ця сторінка тільки для Адміністраторів.")
    st.stop()
# ----------------------------------
make_sidebar()
st.title("📊 Комплексна аналітика бізнесу")

# --- КОНСТАНТИ ---
COMMISSION_RATE = 0.05
COMPANY_EMAIL = 'company@marketplace.com'


# --- ФУНКЦІЯ ЕКСПОРТУ (Щоб не дублювати код) ---
def render_export_buttons(df, filename_prefix):
    st.subheader("📥 Експорт звіту")
    col1, col2 = st.columns(2)

    with col1:
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Завантажити CSV",
            data=csv,
            file_name=f"{filename_prefix}.csv",
            mime="text/csv",
            key=f"csv_{filename_prefix}"
        )

    with col2:
        json_str = df.to_json(orient="records", date_format="iso")
        st.download_button(
            label="Завантажити JSON",
            data=json_str,
            file_name=f"{filename_prefix}.json",
            mime="application/json",
            key=f"json_{filename_prefix}"
        )


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

# Логування
if 'analytics_logged' not in st.session_state:
    log_action(st.session_state['user_id'], "VIEW", "Analytics", None, f"Перегляд звіту {start_date}-{end_date}")
    st.session_state['analytics_logged'] = True

# --- ВКЛАДКИ ---
tab1, tab2, tab3 = st.tabs(["💰 Фінанси & Операції", "🚗 Популярність Авто", "👥 Ефективність Менеджерів"])

# ========================================================
# 1. ФІНАНСОВА ТА ОПЕРАЦІЙНА АНАЛІТИКА
# ========================================================
with tab1:
    st.header("💰 Фінанси та Операції")

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
            SUM(COALESCE(CASE WHEN dd.is_company_deal THEN dd.final_price - lbc.cost_price ELSE 0 END, 0))::bigint AS resale_margin,
            SUM(CASE WHEN NOT dd.is_company_deal THEN dd.final_price * {COMMISSION_RATE} ELSE 0 END)::bigint AS commission_revenue,
            SUM(dd.final_price)::bigint AS total_turnover,
            COUNT(CASE WHEN dd.is_company_deal THEN 1 END) AS count_tradein,
            COUNT(CASE WHEN NOT dd.is_company_deal THEN 1 END) AS count_p2p,
            COUNT(dd.deal_id) AS total_deals
        FROM DealDetails dd
        LEFT JOIN LatestBuybackCosts lbc ON dd.car_id = lbc.car_id
        GROUP BY sales_month
        ORDER BY sales_month ASC;
    """
    df_fin = run_query(finance_query, fetch="all")

    if df_fin is not None and not df_fin.empty:
        df_fin['Net Income'] = df_fin['resale_margin'] + df_fin['commission_revenue']
        total_turnover = df_fin['total_turnover'].sum()
        total_deals_count = df_fin['total_deals'].sum()
        avg_check = total_turnover / total_deals_count if total_deals_count > 0 else 0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Чистий прибуток", f"${df_fin['Net Income'].sum():,.0f}")
        m2.metric("Оборот платформи", f"${total_turnover:,.0f}")
        m3.metric("Всього угод", f"{total_deals_count}")
        m4.metric("Середній чек", f"${avg_check:,.0f}")

        st.divider()

        g1, g2 = st.columns(2)
        with g1:
            df_income_chart = df_fin.rename(
                columns={'resale_margin': 'Маржа (Trade-in)', 'commission_revenue': 'Комісія (P2P)'})
            fig_income = px.bar(df_income_chart, x='sales_month', y=['Маржа (Trade-in)', 'Комісія (P2P)'],
                                title="💵 Структура чистого доходу ($)", barmode='group',
                                color_discrete_map={'Маржа (Trade-in)': '#00CC96', 'Комісія (P2P)': '#636EFA'})
            st.plotly_chart(fig_income, use_container_width=True)

        with g2:
            df_count_chart = df_fin.rename(columns={'count_tradein': 'Угоди Trade-in', 'count_p2p': 'Угоди P2P'})
            fig_count = px.bar(df_count_chart, x='sales_month', y=['Угоди Trade-in', 'Угоди P2P'],
                               title="🤝 Кількість угод (шт.)", barmode='group',
                               color_discrete_map={'Угоди Trade-in': '#00CC96', 'Угоди P2P': '#AB63FA'})
            st.plotly_chart(fig_count, use_container_width=True)

        # ЕКСПОРТ (TAB 1)
        render_export_buttons(df_fin, "finance_report")

    else:
        st.warning("Немає фінансових даних за цей період.")

# ========================================================
# 2. АНАЛІТИКА ПО БРЕНДАХ
# ========================================================
with tab2:
    st.header("Топ продажів за марками")
    brand_query = f"""
        SELECT b.name AS brand_name, COUNT(d.deal_id) AS deals_count, SUM(d.final_price) AS total_volume
        FROM public."Deals" d
        JOIN public."Sale_Announcements" sa ON d.announcement_id = sa.announcement_id
        JOIN public."Cars" c ON sa.car_id = c.car_id
        JOIN public."Models" m ON c.model_id = m.model_id
        JOIN public."Brands" b ON m.brand_id = b.brand_id
        WHERE d.deal_date BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY b.name ORDER BY deals_count DESC LIMIT 10;
    """
    df_brands = run_query(brand_query, fetch="all")

    if df_brands is not None and not df_brands.empty:
        c1, c2 = st.columns([1, 2])
        with c1:
            st.dataframe(df_brands, hide_index=True)
        with c2:
            fig_pie = px.pie(df_brands, values='deals_count', names='brand_name', title="Частка брендів", hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)

        # ЕКСПОРТ (TAB 2)
        render_export_buttons(df_brands, "brands_report")
    else:
        st.info("Недостатньо даних.")

# ========================================================
# 3. ЕФЕКТИВНІСТЬ МЕНЕДЖЕРІВ
# ========================================================
with tab3:
    st.header("KPI Менеджерів")
    manager_query = f"""
        SELECT e.first_name || ' ' || e.last_name AS manager_name,
            COUNT(br.request_id) AS completed_buybacks,
            AVG(br.offer_price)::numeric(10,2) AS avg_buy_price
        FROM public."Buyback_Requests" br
        JOIN public."Employees" e ON br.manager_id = e.employee_id
        WHERE br.status = 'completed'
        GROUP BY manager_name ORDER BY completed_buybacks DESC;
    """
    df_managers = run_query(manager_query, fetch="all")

    if df_managers is not None and not df_managers.empty:
        fig_mgr = px.bar(
            df_managers, x='completed_buybacks', y='manager_name', orientation='h',
            title="Топ менеджерів (Trade-in)", color='completed_buybacks', color_continuous_scale='Viridis'
        )
        st.plotly_chart(fig_mgr, use_container_width=True)

        # ЕКСПОРТ (TAB 3)
        render_export_buttons(df_managers, "managers_kpi")
    else:
        st.info("Немає даних.")