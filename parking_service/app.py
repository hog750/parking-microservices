from flask import Flask, request, jsonify
import pyodbc
import datetime
import requests

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecretkey"

AUTH_URL = "http://auth_service:5001/auth/verify"
VEHICLE_URL = "http://vehicle_service:5002"
TARIFF_URL = "http://tariff_service:5011"
NOTIFY_URL = "http://notification_service:5012/notify"


# ----------------------------------------------------------------------
# Подключение к БД ParkingDB2
# ----------------------------------------------------------------------
def get_db_connection():
    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=host.docker.internal,1433;"
        "DATABASE=ParkingDB2;"
        "UID=sa;"
        "PWD=SaPass123!;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


# ----------------------------------------------------------------------
# Утилиты
# ----------------------------------------------------------------------
def send_notification(n_type: str, message: str):
    try:
        requests.post(
            NOTIFY_URL,
            json={"type": n_type, "message": message},
            timeout=2
        )
    except Exception:
        # уведомление не критично, игнорим
        pass


def verify_token(token_header: str):
    """Проверка токена через Auth Service. Возвращает username или None."""
    if not token_header:
        return None

    token = token_header
    if token.startswith("Bearer "):
        token = token.replace("Bearer ", "", 1)

    try:
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get(AUTH_URL, headers=headers, timeout=5)
        data = res.json()
        if res.status_code == 200 and data.get("valid"):
            return data.get("user")
        return None
    except Exception as e:
        print(f"[AUTH ERROR] {e}")
        return None


def get_user_vehicle(token_header: str):
    """Берём первую машину пользователя из vehicle_service."""
    try:
        headers = {"Authorization": token_header}
        res = requests.get(f"{VEHICLE_URL}/vehicle/mine", headers=headers, timeout=5)
        if res.status_code != 200:
            print(f"[VEHICLE ERROR] status {res.status_code}")
            return None
        vehicles = res.json()
        if isinstance(vehicles, list) and len(vehicles) > 0:
            return vehicles[0]["license_plate"]
        print("[VEHICLE] No vehicles found for user")
        return None
    except Exception as e:
        print(f"[VEHICLE ERROR] {e}")
        return None


def calc_fee_via_tariff(total_minutes: float) -> float:
    """Запрашиваем у tariff_service стоимость по количеству минут."""
    try:
        minutes_int = int(round(total_minutes))
        r = requests.get(
            f"{TARIFF_URL}/tariffs/calc",
            params={"minutes": minutes_int},
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            return float(data.get("fee", 0))
        else:
            print(f"[TARIFF ERROR] status {r.status_code}")
            return 0.0
    except Exception as e:
        print(f"[TARIFF ERROR] {e}")
        return 0.0


# ----------------------------------------------------------------------
# Начало парковки
# ----------------------------------------------------------------------
@app.route("/parking/start", methods=["POST"])
def start_parking():
    auth_header = request.headers.get("Authorization", "")
    user = verify_token(auth_header)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    slot_id = data.get("slot_id")
    if not slot_id:
        return jsonify({"error": "Missing slot_id"}), 400

    license_plate = get_user_vehicle(auth_header)
    if not license_plate:
        return jsonify({"error": "No registered vehicles for this user"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT status FROM ParkingSlots WHERE slot_id = ?", (slot_id,))
        result = cursor.fetchone()
        if not result or result[0] != "Available":
            cursor.close()
            conn.close()
            return jsonify({"error": "Slot unavailable"}), 400

        # помечаем слот занятым
        cursor.execute("UPDATE ParkingSlots SET status='Occupied' WHERE slot_id=?", (slot_id,))

        # создаём сессию
        now = datetime.datetime.now()
        cursor.execute(
            """
            INSERT INTO Sessions (vehicle_id, slot_id, entry_time, user_name)
            VALUES (?, ?, ?, ?)
            """,
            (license_plate, slot_id, now, user)
        )
        conn.commit()

        cursor.execute(
            "SELECT id FROM Sessions WHERE vehicle_id=? AND slot_id=? AND entry_time=?",
            (license_plate, slot_id, now)
        )
        row = cursor.fetchone()
        session_id = str(row[0]) if row else None

        cursor.close()
        conn.close()

        send_notification(
            "parking_entry",
            f"Vehicle {license_plate} started parking at slot {slot_id} (user {user})"
        )

        return jsonify({
            "message": f"Vehicle {license_plate} parked at slot {slot_id} by {user}",
            "session_id": session_id
        }), 200

    except Exception as e:
        print(f"[DB ERROR] {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500


# ----------------------------------------------------------------------
# Завершение парковки
# ----------------------------------------------------------------------
@app.route("/parking/stop", methods=["POST"])
def stop_parking():
    auth_header = request.headers.get("Authorization", "")
    user = verify_token(auth_header)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    license_plate = get_user_vehicle(auth_header)
    if not license_plate:
        return jsonify({"error": "No registered vehicles for this user"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, entry_time, slot_id FROM Sessions WHERE vehicle_id=? AND exit_time IS NULL",
            (license_plate,)
        )
        session = cursor.fetchone()

        if not session:
            cursor.close()
            conn.close()
            return jsonify({"error": "No active session"}), 404

        session_id, entry_time, slot_id = session
        now = datetime.datetime.now()
        duration_minutes = (now - entry_time).total_seconds() / 60.0

        fee = calc_fee_via_tariff(duration_minutes)

        cursor.execute(
            "UPDATE Sessions SET exit_time=?, amount=?, total_minutes=? WHERE id=?",
            (now, fee, duration_minutes, session_id)
        )
        cursor.execute(
            "UPDATE ParkingSlots SET status='Available' WHERE slot_id=?",
            (slot_id,)
        )
        conn.commit()

        cursor.close()
        conn.close()

        send_notification(
            "parking_exit",
            f"Vehicle {license_plate} left slot {slot_id}, minutes={duration_minutes:.1f}, fee={fee}"
        )

        return jsonify({
            "message": "Parking session closed",
            "session_id": str(session_id),
            "total_minutes": round(duration_minutes, 2),
            "fee": float(fee)
        }), 200

    except Exception as e:
        print(f"[DB ERROR] {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500


# ----------------------------------------------------------------------
# Список парковочных слотов
# ----------------------------------------------------------------------
@app.route("/parking/slots", methods=["GET"])
def get_slots():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT slot_id, status FROM ParkingSlots")
        slots = [{"slot_id": row[0], "status": row[1]} for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify(slots), 200
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500


# ----------------------------------------------------------------------
# Активные сессии (для админа)
# ----------------------------------------------------------------------
@app.route("/parking/active_sessions", methods=["GET"])
def active_sessions():
    """Все незакрытые сессии + расчёт текущего ожидаемого тарифа."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, vehicle_id, slot_id, entry_time, user_name
            FROM Sessions
            WHERE exit_time IS NULL
            """
        )
        rows = cursor.fetchall()
        now = datetime.datetime.now()

        sessions = []
        for r in rows:
            session_id = r[0]
            plate = r[1]
            slot_id = r[2]
            entry_time = r[3]
            user_name = r[4]

            minutes = (now - entry_time).total_seconds() / 60.0
            fee = calc_fee_via_tariff(minutes)

            sessions.append({
                "session_id": str(session_id),
                "vehicle_id": plate,
                "slot_id": slot_id,
                "user_name": user_name,
                "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "minutes": round(minutes, 1),
                "expected_fee": float(fee)
            })

        cursor.close()
        conn.close()
        return jsonify(sessions), 200

    except Exception as e:
        print(f"[DB ERROR] {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500


# ----------------------------------------------------------------------
# Информация по сессии (для payment_service)
# ----------------------------------------------------------------------
@app.route("/parking/session/<session_id>", methods=["GET"])
def session_summary(session_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT id, vehicle_id, slot_id, entry_time, exit_time, user_name, total_minutes, amount
            FROM Sessions WHERE id = ?
            """,
            (session_id,)
        )
        r = cursor.fetchone()
        if not r:
            cursor.close()
            conn.close()
            return jsonify({"error": "Session not found"}), 404

        sid, plate, slot_id, entry, exit_time, user_name, total_minutes, amount = r
        now = datetime.datetime.now()

        if exit_time:
            minutes = (exit_time - entry).total_seconds() / 60.0
        else:
            minutes = (now - entry).total_seconds() / 60.0

        fee = calc_fee_via_tariff(minutes)

        cursor.close()
        conn.close()

        return jsonify({
            "session_id": str(sid),
            "vehicle_id": plate,
            "slot_id": slot_id,
            "user_name": user_name,
            "entry_time": entry.strftime("%Y-%m-%d %H:%M:%S"),
            "exit_time": exit_time.strftime("%Y-%m-%d %H:%M:%S") if exit_time else None,
            "total_minutes": round(minutes, 2),
            "calculated_fee": float(fee),
            "stored_amount": float(amount) if amount is not None else None
        }), 200

    except Exception as e:
        print(f"[DB ERROR] {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500


# ----------------------------------------------------------------------
# Последняя завершённая сессия пользователя (для /pay)
# ----------------------------------------------------------------------
@app.route("/parking/my_last_session", methods=["GET"])
def my_last_session():
    auth_header = request.headers.get("Authorization", "")
    user = verify_token(auth_header)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT TOP 1 id, vehicle_id, slot_id, entry_time, exit_time, total_minutes, amount
            FROM Sessions
            WHERE user_name = ? AND exit_time IS NOT NULL
            ORDER BY exit_time DESC
            """,
            (user,)
        )
        r = cursor.fetchone()
        if not r:
            cursor.close()
            conn.close()
            return jsonify({"error": "No finished sessions found"}), 404

        sid, plate, slot_id, entry, exit_time, total_minutes, amount = r

        if total_minutes is None:
            minutes = (exit_time - entry).total_seconds() / 60.0
        else:
            minutes = float(total_minutes)

        fee = calc_fee_via_tariff(minutes)

        cursor.close()
        conn.close()

        return jsonify({
            "session_id": str(sid),
            "vehicle_id": plate,
            "slot_id": slot_id,
            "entry_time": entry.strftime("%Y-%m-%d %H:%M:%S"),
            "exit_time": exit_time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_minutes": round(minutes, 2),
            "calculated_fee": float(fee)
        }), 200

    except Exception as e:
        print(f"[DB ERROR] {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)
