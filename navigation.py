import streamlit as st
from time import sleep


def make_sidebar():
    """Малює бічну панель навігації залежно від ролі."""

    # Якщо стилі не підвантажились або юзер не залогінений - нічого не малюємо
    if 'role' not in st.session_state or st.session_state['role'] is None:
        return

    with st.sidebar:
        st.title(f"👤 {st.session_state.get('username', 'Користувач')}")
        st.caption(f"Роль: {st.session_state['role'].upper()}")
        st.divider()

        # --- КНОПКИ НАВІГАЦІЇ ---

        # Кнопка "На Головну" (доступна всім)
        st.page_link("main.py", label="Головна панель", icon="🏠")
        st.divider()

        role = st.session_state['role']

        # Меню КЛІЄНТА
        if role == 'client':
            st.page_link("pages/MyGarage.py", label="Мій Гараж", icon="🚗")
            st.page_link("pages/Announcements.py", label="Всі Оголошення", icon="📢")

        # Меню МЕНЕДЖЕРА
        elif role == 'manager':
            st.page_link("pages/BuybackRequests.py", label="Заявки на викуп", icon="📥")
            st.page_link("pages/Inspections.py", label="Інспекції", icon="🔧")
            st.page_link("pages/Deals.py", label="Угоди", icon="🤝")
            st.page_link("pages/Cars.py", label="База Авто", icon="🚘")
            st.page_link("pages/Announcements.py", label="Всі Оголошення", icon="📢")

        # Меню АДМІНІСТРАТОРА
        elif role == 'admin':
            st.write("📊 **Аналітика**")
            st.page_link("pages/Analytics.py", label="Звіти та KPI", icon="📈")
            st.page_link("pages/Audit_Logs.py", label="Аудит дій", icon="🛡️")

            st.write("👥 **Персонал**")
            st.page_link("pages/Employees.py", label="Співробітники", icon="🧑‍💼")

            st.write("⚙️ **Робочі процеси**")
            st.page_link("pages/BuybackRequests.py", label="Заявки", icon="📥")
            st.page_link("pages/Deals.py", label="Угоди", icon="🤝")
            st.page_link("pages/Cars.py", label="Автомобілі", icon="🚘")
            st.page_link("pages/Inspections.py", label="Інспекції", icon="🔧")
            st.page_link("pages/Announcements.py", label="Оголошення", icon="📢")

        # --- КНОПКА ВИХОДУ (В самому низу) ---
        st.divider()
        if st.button("Вийти з системи", type="primary"):
            st.session_state['user_id'] = None
            st.session_state['role'] = None
            st.session_state['username'] = None
            st.success("Вихід...")
            sleep(0.5)
            st.switch_page("main.py")