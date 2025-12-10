import streamlit as st
from auth import login_user, register_user
from navigation import make_sidebar  # <--- ІМПОРТУЄМО НАВІГАЦІЮ
import time

# Налаштування сторінки має бути першим
st.set_page_config(page_title="Car Marketplace", page_icon="🚗", layout="centered")

# --- ІНІЦІАЛІЗАЦІЯ СЕСІЇ ---
if 'user_id' not in st.session_state:
    st.session_state['user_id'] = None
if 'role' not in st.session_state:
    st.session_state['role'] = None
if 'username' not in st.session_state:
    st.session_state['username'] = None


# --- ФУНКЦІЯ ВИХОДУ ---
def logout():
    st.session_state['user_id'] = None
    st.session_state['role'] = None
    st.session_state['username'] = None
    st.rerun()


# ==========================================
# 1. ЛОГІКА НЕАВТОРИЗОВАНОГО КОРИСТУВАЧА
# ==========================================
if st.session_state['user_id'] is None:
    st.title("🚗 Автомобільний Маркетплейс")
    st.info("Будь ласка, увійдіть в систему або зареєструйтесь.")

    tab1, tab2 = st.tabs(["🔐 Вхід", "📝 Реєстрація"])

    # --- ВХІД ---
    with tab1:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Пароль", type="password")
            submit_login = st.form_submit_button("Увійти")

            if submit_login:
                user = login_user(email, password)
                if user:
                    st.session_state['user_id'] = user['id']
                    st.session_state['role'] = user['role']
                    st.session_state['username'] = user['name']
                    st.success(f"Вітаємо, {user['name']}! ({user['role']})")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Невірний email або пароль.")

    # --- РЕЄСТРАЦІЯ ---
    with tab2:
        with st.form("register_form"):
            new_first = st.text_input("Ім'я")
            new_last = st.text_input("Прізвище")
            new_email = st.text_input("Email")
            new_phone = st.text_input("Телефон")
            new_pass = st.text_input("Пароль", type="password")
            submit_reg = st.form_submit_button("Зареєструватися")

            if submit_reg:
                if register_user(new_first, new_last, new_email, new_phone, new_pass):
                    st.success("Акаунт створено! Тепер ви можете увійти.")
                else:
                    st.error("Помилка при створенні акаунту. Можливо, такий email вже існує.")

# ==========================================
# 2. ЛОГІКА АВТОРИЗОВАНОГО КОРИСТУВАЧА (МЕНЮ)
# ==========================================
else:
    # 1. МАЛЮЄМО БІЧНУ ПАНЕЛЬ (Імпортована функція)
    make_sidebar()

    # 2. ГОЛОВНА СТОРІНКА (Контент по центру)
    st.title(f"Ласкаво просимо, {st.session_state['username']}!")

    st.markdown("---")
    st.markdown("### 🏠 Панель керування")
    st.write("Оберіть потрібний розділ у меню зліва.")

    role = st.session_state['role']

    if role == 'client':
        st.info("🛍️ **Для Клієнтів:**")
        st.write("- **Мій Гараж**: Керуйте своїми авто та заявками.")
        st.write("- **Оголошення**: Шукайте авто для купівлі.")

    elif role == 'manager':
        st.info("💼 **Для Менеджерів:**")
        st.write("- **Заявки**: Обробка Trade-in запитів.")
        st.write("- **Інспекції**: Проведення тех. огляду.")
        st.write("- **Угоди**: Оформлення купівлі-продажу.")

    elif role == 'admin':
        st.info("🛡️ **Для Адміністратора:**")
        st.write("- **Аналітика**: Фінансові звіти та KPI.")
        st.write("- **Аудит**: Перегляд логів дій користувачів.")
        st.write("- **Співробітники**: Управління доступом персоналу.")