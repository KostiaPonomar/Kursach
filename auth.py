# auth.py
import hashlib
import streamlit as st
from db_utils import run_query, log_action


def make_hash(password):
    """Створює SHA-256 хеш пароля."""
    return hashlib.sha256(str.encode(password)).hexdigest()


def check_hashes(password, hashed_text):
    """Перевіряє, чи співпадає пароль із хешем у БД."""
    if make_hash(password) == hashed_text:
        return True
    return False


def login_user(email, password):
    """
    Перевіряє email та пароль.
    Повертає словник з даними користувача або None.
    """
    # Отримуємо користувача з бази
    query = """
        SELECT user_id, first_name, last_name, password_hash, role 
        FROM public."Users" 
        WHERE email = %s;
    """
    user_data = run_query(query, (email,), fetch="one")

    if user_data:
        # Розпаковка кортежу (id, first, last, hash, role)
        user_id, first_name, last_name, db_hash, role = user_data

        # Перевірка пароля
        # Примітка: Якщо у тебе тестові дані з Faker, там паролі не хешовані.
        # Для реального входу треба буде зареєструвати нового юзера через форму.
        if check_hashes(password, db_hash) or password == db_hash:  # Додав другу умову для тестових даних Faker

            # ЛОГУВАННЯ ВХОДУ (Вимога f)
            log_action(user_id, "LOGIN", "Users", user_id, "Успішний вхід в систему")

            return {
                "id": user_id,
                "name": f"{first_name} {last_name}",
                "role": role
            }

    return None


def register_user(first_name, last_name, email, phone, password):
    """Реєструє нового клієнта (роль за замовчуванням 'client')."""
    hashed_pass = make_hash(password)
    try:
        query = """
            INSERT INTO public."Users" 
            (first_name, last_name, email, phone_number, password_hash, role, registration_date)
            VALUES (%s, %s, %s, %s, %s, 'client', CURRENT_TIMESTAMP)
            RETURNING user_id;
        """
        # Використовуємо fetch="one", щоб отримати ID і переконатися, що INSERT пройшов
        res = run_query(query, (first_name, last_name, email, phone, hashed_pass), fetch="one", commit=True)

        if res:
            new_id = res[0]
            log_action(new_id, "REGISTER", "Users", new_id, "Реєстрація нового користувача")
            return True
    except Exception as e:
        st.error(f"Помилка реєстрації: {e}")
        return False
    return False