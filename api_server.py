from fastapi import FastAPI, HTTPException, Depends, Header, Query, Path, Body
from pydantic import BaseModel, Field
import psycopg2
from psycopg2.extras import RealDictCursor
from config import DB_CONFIG
from typing import List, Optional
from datetime import datetime

# Ініціалізація додатку
app = FastAPI(
    title="Car Marketplace API (Ultimate)",
    description="Професійний API для інтеграції з партнерами, CRM та мобільними додатками.",
    version="3.0.0"
)

# --- 🔒 БЕЗПЕКА (API Key) ---
API_KEY = "partner-secret-123"


async def verify_api_key(x_api_key: str = Header(..., description="Секретний ключ партнера")):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Невірний API ключ. Доступ заборонено.")
    return x_api_key


# --- 📦 МОДЕЛІ ДАНИХ (Pydantic) ---
class CarEstimateRequest(BaseModel):
    brand: str
    model: str
    year: int
    mileage: int


class TestDriveRequest(BaseModel):
    car_id: int = Field(..., description="ID оголошення або авто з каталогу")
    client_name: str
    client_phone: str
    preferred_date: str = Field(..., example="2024-06-01")


class UserContactUpdate(BaseModel):
    email: str
    new_phone: str


# --- 🔌 ПІДКЛЮЧЕННЯ ДО БД ---
def get_db():
    try:
        return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {e}")


# ==============================================================================
# 🟢 ГРУПА 1: ПУБЛІЧНИЙ КАТАЛОГ (GET)
# ==============================================================================

@app.get("/api/v1/catalog/export", tags=["Public Data"])
def get_active_listings(
        min_price: Optional[float] = Query(None),
        brand: Optional[str] = Query(None)
):
    """
    **Експорт каталогу.**
    Використовується партнерами (Auto.ria, OLX) для отримання списку наших активних авто.
    """
    conn = get_db()
    cur = conn.cursor()
    try:
        query = """
            SELECT sa.announcement_id, b.name as brand, m.name as model, c.year, c.vin_code, sa.price, sa.description
            FROM public."Sale_Announcements" sa
            JOIN public."Cars" c ON sa.car_id = c.car_id
            JOIN public."Models" m ON c.model_id = m.model_id
            JOIN public."Brands" b ON m.brand_id = b.brand_id
            WHERE sa.status = 'active'
        """
        params = []
        if min_price:
            query += " AND sa.price >= %s"
            params.append(min_price)
        if brand:
            query += " AND b.name ILIKE %s"
            params.append(f"%{brand}%")

        query += " ORDER BY sa.creation_date DESC"

        cur.execute(query, tuple(params))
        return {"timestamp": datetime.now(), "data": cur.fetchall()}
    finally:
        cur.close();
        conn.close()


@app.get("/api/v1/check/vin/{vin_code}", tags=["Public Data"])
def check_car_by_vin(vin_code: str = Path(..., min_length=17, max_length=17)):
    """
    **Перевірка авто за VIN.**
    Дозволяє дізнатися, чи продається авто з таким VIN у нас на майданчику.
    """
    conn = get_db()
    cur = conn.cursor()
    try:
        query = """
            SELECT c.car_id, b.name, m.name as model, sa.price, sa.status
            FROM "Cars" c
            JOIN "Models" m ON c.model_id = m.model_id
            JOIN "Brands" b ON m.brand_id = b.brand_id
            LEFT JOIN "Sale_Announcements" sa ON c.car_id = sa.car_id
            WHERE c.vin_code = %s
        """
        cur.execute(query, (vin_code,))
        res = cur.fetchone()

        if not res:
            return {"found": False, "message": "Авто не знайдено в нашій базі."}

        return {
            "found": True,
            "car": f"{res['name']} {res['model']}",
            "is_active_sale": res['status'] == 'active',
            "price": res['price']
        }
    finally:
        cur.close();
        conn.close()


# ==============================================================================
# 🔵 ГРУПА 2: ДОВІДНИКИ (GET)
# ==============================================================================

@app.get("/api/v1/dict/brands", tags=["Dictionaries"])
def get_brands():
    """Список брендів для випадаючих списків."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('SELECT brand_id, name FROM "Brands" ORDER BY name')
        return cur.fetchall()
    finally:
        cur.close();
        conn.close()


@app.get("/api/v1/dict/models/{brand_id}", tags=["Dictionaries"])
def get_models(brand_id: int):
    """Список моделей для обраного бренду."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('SELECT model_id, name FROM "Models" WHERE brand_id = %s ORDER BY name', (brand_id,))
        return cur.fetchall()
    finally:
        cur.close();
        conn.close()


# ==============================================================================
# 🟠 ГРУПА 3: БІЗНЕС-ЛОГІКА (POST) - Захищено API Key
# ==============================================================================

@app.post("/api/v1/leads/estimate", tags=["Integration"], dependencies=[Depends(verify_api_key)])
def estimate_car_value(req: CarEstimateRequest):
    """
    **Trade-in Калькулятор (AI Estimate).**
    Аналізує базу даних, знаходить середню ціну схожих авто і пропонує вартість викупу.
    """
    conn = get_db()
    cur = conn.cursor()
    try:
        # 1. Рахуємо середню ринкову ціну в базі
        cur.execute("""
            SELECT AVG(sa.price) as avg_price 
            FROM "Sale_Announcements" sa
            JOIN "Cars" c ON sa.car_id = c.car_id
            JOIN "Models" m ON c.model_id = m.model_id
            JOIN "Brands" b ON m.brand_id = b.brand_id
            WHERE b.name ILIKE %s AND m.name ILIKE %s
        """, (req.brand, req.model))

        res = cur.fetchone()
        base = float(res['avg_price']) if res and res['avg_price'] else 15000.0  # Дефолт

        # 2. Амортизація (-5% за рік)
        age = 2024 - req.year
        estimated = round(base * (0.95 ** age), 2)
        trade_in = round(estimated * 0.85, 2)

        # 3. Логуємо лід
        log_msg = f"API ESTIMATE REQUEST: {req.brand} {req.model} ({req.year})"
        cur.execute(
            "INSERT INTO \"Audit_Logs\" (action_type, table_name, details, timestamp) VALUES ('EXTERNAL_LEAD', 'Integration', %s, NOW())",
            (log_msg,))
        conn.commit()

        return {
            "status": "success",
            "valuation": {
                "market_price": estimated,
                "trade_in_offer": trade_in,
                "currency": "USD"
            }
        }
    finally:
        cur.close();
        conn.close()


@app.post("/api/v1/services/test-drive", tags=["Integration"])
def book_test_drive(req: TestDriveRequest):
    """
    **Запис на Тест-драйв.**
    Перевіряє, чи авто ще в продажу. Якщо так — створює заявку.
    """
    conn = get_db()
    cur = conn.cursor()
    try:
        # 1. Перевірка наявності авто
        cur.execute("""
            SELECT sa.title, sa.price, u.email as seller_email
            FROM "Sale_Announcements" sa
            JOIN "Users" u ON sa.seller_user_id = u.user_id
            WHERE sa.car_id = %s AND sa.status = 'active'
        """, (req.car_id,))

        car = cur.fetchone()

        if not car:
            raise HTTPException(status_code=404, detail="Авто не знайдено або вже продано.")

        # 2. Реєстрація заявки (в Audit Logs як імітація CRM)
        log_msg = f"TEST-DRIVE: {req.client_name} ({req.client_phone}) -> {car['title']} on {req.preferred_date}"

        cur.execute("""
            INSERT INTO "Audit_Logs" (action_type, table_name, record_id, details, timestamp)
            VALUES ('TEST_DRIVE', 'Cars', %s, %s, NOW())
        """, (req.car_id, log_msg))

        conn.commit()

        return {
            "status": "confirmed",
            "message": f"Заявку на огляд {car['title']} прийнято. Менеджер зв'яжеться з вами."
        }
    finally:
        cur.close();
        conn.close()


# ==============================================================================
# 🔴 ГРУПА 4: УПРАВЛІННЯ ДАНИМИ (PUT)
# ==============================================================================

@app.put("/api/v1/users/contact", tags=["Integration"], dependencies=[Depends(verify_api_key)])
def update_user_contact(data: UserContactUpdate):
    """
    **Оновлення контактів.**
    Дозволяє змінити номер телефону клієнта через зовнішню систему (наприклад, мобільний додаток).
    """
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('UPDATE "Users" SET phone_number = %s WHERE email = %s RETURNING user_id',
                    (data.new_phone, data.email))
        res = cur.fetchone()
        conn.commit()

        if not res:
            raise HTTPException(status_code=404, detail="Користувача не знайдено")

        return {"status": "success", "message": f"Телефон оновлено для {data.email}"}
    finally:
        cur.close();
        conn.close()


# --- ЗАПУСК ---
if __name__ == "__main__":
    import uvicorn

    print("🚀 Сервер запущено! Відкрийте документацію: http://127.0.0.1:8000/docs")
    uvicorn.run(app, host="127.0.0.1", port=8000)