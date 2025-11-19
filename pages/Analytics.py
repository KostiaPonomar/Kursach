import streamlit as st
from db_utils import run_query
import datetime
import pandas as pd

st.set_page_config(page_title="Аналітика", layout="wide")
st.title("📊 Аналітика бізнесу")

# --- НАЛАШТУВАННЯ ---
COMMISSION_RATE = 0.05
COMPANY_EMAIL = 'company@marketplace.com'
# --------------------

st.sidebar.header("Фільтри аналітики")
today = datetime.date.today()
year_ago = today - datetime.timedelta(days=365)
date_range = st.sidebar.date_input(
    "Оберіть проміжок часу:", value=(year_ago, today),
    min_value=year_ago - datetime.timedelta(days=365 * 2), max_value=today
)

if len(date_range) == 2:
    start_date, end_date = date_range

    st.subheader(f"Звіт по ефективності з {start_date} по {end_date}")

    # Запит залишається той самий, він вже містить усі потрібні дані для нових розрахунків
    analytics_query = f"""
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
            -- Використовуємо попередню, більш надійну версію з ранжуванням
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

            -- === КЛЮЧОВЕ ВИПРАВЛЕННЯ: Обгортаємо розрахунок прибутку в COALESCE ===
            SUM(
                COALESCE(
                    CASE 
                        WHEN dd.is_company_deal THEN dd.final_price - lbc.cost_price 
                        ELSE 0 
                    END, 0)
            )::bigint AS total_profit,
            -- ======================================================================

            SUM(CASE WHEN NOT dd.is_company_deal THEN dd.final_price * {COMMISSION_RATE} ELSE 0 END)::bigint AS total_commission,

            -- Додаємо ці поля знову для фінальної таблиці
            COUNT(dd.deal_id) AS total_deals,
            SUM(dd.final_price)::bigint AS total_revenue_all,
            SUM(CASE WHEN dd.is_company_deal THEN dd.final_price ELSE 0 END)::bigint AS total_revenue_company

        FROM DealDetails dd
        LEFT JOIN LatestBuybackCosts lbc ON dd.car_id = lbc.car_id
        GROUP BY sales_month
        ORDER BY sales_month ASC;
        """

    analytics_df = run_query(analytics_query, fetch="all")

    if analytics_df is not None and not analytics_df.empty:
        analytics_df.set_index('sales_month', inplace=True)
        analytics_df['total_company_income'] = analytics_df['total_profit'] + analytics_df['total_commission']

        # --- ВІДОБРАЖЕННЯ МЕТРИК ---
        total_profit = analytics_df['total_profit'].sum()
        total_commission = analytics_df['total_commission'].sum()
        total_income = analytics_df['total_company_income'].sum()

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Прибуток від перепродажу", value=f"${int(total_profit):,}")
        with col2:
            st.metric("Дохід від комісій", value=f"${int(total_commission):,}")
        with col3:
            st.metric("ЗАГАЛЬНИЙ ДОХІД КОМПАНІЇ", value=f"${int(total_income):,}")

        st.subheader("Структура доходу компанії по місяцях")
        st.bar_chart(analytics_df[['total_profit', 'total_commission']])

        st.subheader("Динаміка загального доходу")
        st.line_chart(analytics_df[['total_company_income']])

        # --- НОВИЙ ГРАФІК: КІЛЬКІСТЬ УГОД ---
        st.subheader("Кількість угод по місяцях (загальна)")
        st.line_chart(analytics_df[['total_deals']])
        # -----------------------------------

        # --- НОВА ФІНАЛЬНА ТАБЛИЦЯ ---
        st.subheader("Підсумковий звіт за обраний період")

        # Готуємо дані для нової таблиці
        summary_data = {
            "Показник": [
                "Сума всіх продажів на платформі",
                "Сума продажів викуплених авто (дохід компанії)",
                "Сума прибутку від комісій",
                "Загальна кількість проданих авто"
            ],
            "Значення": [
                f"${int(analytics_df['total_revenue_all'].sum()):,}",
                f"${int(analytics_df['total_revenue_company'].sum()):,}",
                f"${int(analytics_df['total_commission'].sum()):,}",
                f"{int(analytics_df['total_deals'].sum())}"
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        st.table(summary_df)
        # --------------------------------

    else:
        st.warning("За обраний період даних для аналізу доходу не знайдено.")