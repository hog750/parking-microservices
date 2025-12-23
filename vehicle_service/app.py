from flask import Flask, request, jsonify
import os
import uuid
from datetime import datetime
import pyodbc
import requests

app = Flask(__name__)

# ====== Конфиг через переменные окружения (с дефолтами) ======
DB_SERVER   = os.getenv("DB_SERVER",   "192.168.0.123")  # в Docker переопределим на host.docker.internal
DB_NAME     = os.getenv("DB_NAME",     "VehicleDB")
DB_USER     = os.getenv("DB_USER",     "sa")
DB_PASSWORD = os.getenv("DB_PASSWORD", "SaPass123!")

AUTH_VERIFY_URL = os.getenv("AUTH_VERIFY_URL", "http://auth_service:5001/auth/verify")


def get_db_connection():
    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={DB_SERVER},1433;"
        f"DATABASE={DB_NAME};"
        f"UID={DB_USER};"
        f"PWD={DB_PASSWORD};"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


# ====== Инициализация схемы ======
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Таблица хранит владельца по username (строкой), чтобы не зависеть от чужой Users-таблицы
    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Vehicles')
        CREATE TABLE Vehicles (
            id            VARCHAR(36)  PRIMARY KEY,
            license_plate VARCHAR(20)  NOT NULL UNIQUE,
            status        VARCHAR(20)  NOT NULL,
            user_name     VARCHAR(50)  NOT NULL,
            created_at    DATETIME      NOT NULL DEFAULT GETDATE()
        );
    """)
    conn.commit()
    cur.close()
    conn.close()


init_db()


# ====== Авторизация через auth_service ======
def verify_token(auth_header: str):
    """
    Возвращает dict: {"valid": bool, "user": <username>|None, "error": str|None}
    """
    if not auth_header:
        return {"valid": False, "user": None, "error": "Missing Authorization header"}

    token = auth_header
    if token.startswith("Bearer "):
        token = token.replace("Bearer ", "", 1)

    try:
        res = requests.get(
            AUTH_VERIFY_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5
        )
        if res.status_code != 200:
            return {"valid": False, "user": None, "error": f"Auth service status {res.status_code}"}
        data = res.json()
        return {"valid": data.get("valid") is True, "user": data.get("user"), "error": None}
    except Exception as e:
        return {"valid": False, "user": None, "error": f"Auth verify failed: {e}"}


# ====== Хелсчек ======
@app.route("/health", methods=["GET"])
def health():
    try:
        conn = get_db_connection()
        conn.close()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "db_error", "details": str(e)}), 500


# ====== Добавить авто (только с валидным токеном) ======
@app.route("/vehicle/add", methods=["POST"])
def add_vehicle():
    auth = verify_token(request.headers.get("Authorization", ""))
    if not auth["valid"]:
        return jsonify({"error": "Unauthorized", "details": auth["error"]}), 401

    data = request.get_json(silent=True) or {}
    license_plate = (data.get("license_plate") or "").strip().upper()

    if not license_plate:
        return jsonify({"error": "Missing license_plate"}), 400

    vehicle_id = str(uuid.uuid4())

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO Vehicles (id, license_plate, status, user_name)
            VALUES (?, ?, ?, ?)
        """, (vehicle_id, license_plate, "Pending", auth["user"]))
        conn.commit()
        return jsonify({"message": "Vehicle registered", "vehicle_id": vehicle_id, "owner": auth["user"]})
    except pyodbc.Error as e:
        return jsonify({"error": "DB error", "details": str(e)})
    finally:
        cur.close()
        conn.close()


# ====== Список авто текущего пользователя ======
@app.route("/vehicle/mine", methods=["GET"])
def get_my_vehicles():
    auth = verify_token(request.headers.get("Authorization", ""))
    if not auth["valid"]:
        return jsonify({"error": "Unauthorized", "details": auth["error"]}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, license_plate, status, user_name, created_at
            FROM Vehicles
            WHERE user_name = ?
            ORDER BY created_at DESC
        """, (auth["user"],))
        rows = cur.fetchall()
        result = [
            {
                "id": r[0],
                "license_plate": r[1],
                "status": r[2],
                "user_name": r[3],
                "created_at": r[4].strftime("%Y-%m-%d %H:%M:%S") if isinstance(r[4], datetime) else str(r[4])
            }
            for r in rows
        ]
        return jsonify(result)
    finally:
        cur.close()
        conn.close()
# ====== /vehicle/register — алиас для совместимости с Dashboard ======
@app.route("/vehicle/register", methods=["POST"])
def register_vehicle_alias():
    # полностью повторяет add_vehicle()
    auth = verify_token(request.headers.get("Authorization", ""))

    if not auth["valid"]:
        return jsonify({"error": "Unauthorized", "details": auth["error"]}), 401

    data = request.get_json(silent=True) or {}
    license_plate = (data.get("license_plate") or "").strip().upper()

    if not license_plate:
        return jsonify({"error": "Missing license_plate"}), 400

    vehicle_id = str(uuid.uuid4())

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO Vehicles (id, license_plate, status, user_name)
            VALUES (?, ?, ?, ?)
        """, (vehicle_id, license_plate, "Pending", auth["user"]))
        conn.commit()

        return jsonify({
            "message": "Vehicle registered",
            "vehicle_id": vehicle_id,
            "owner": auth["user"]
        })
    except pyodbc.Error as e:
        return jsonify({"error": "DB error", "details": str(e)})
    finally:
        cur.close()
        conn.close()


# ====== Статус по id ======
@app.route("/vehicle/status/<vehicle_id>", methods=["GET"])
def get_vehicle_status(vehicle_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT license_plate, status, user_name, created_at
            FROM Vehicles WHERE id = ?
        """, (vehicle_id,))
        r = cur.fetchone()
        if not r:
            return jsonify({"error": "Vehicle not found"}), 404

        return jsonify({
            "license_plate": r[0],
            "status": r[1],
            "user_name": r[2],
            "created_at": r[3].strftime("%Y-%m-%d %H:%M:%S") if isinstance(r[3], datetime) else str(r[3])
        })
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
