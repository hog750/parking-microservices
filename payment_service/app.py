from flask import Flask, request, jsonify
import pyodbc
import datetime
import requests

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecretkey"

AUTH_URL = "http://auth_service:5001/auth/verify"
PARKING_URL = "http://parking_service:5003"
NOTIFY_URL = "http://notification_service:5012/notify"


# ----------------------------------------------------------------------
# Подключение к PaymentDB
# ----------------------------------------------------------------------
def get_db_connection():
    conn_str = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=host.docker.internal,1433;"
        "DATABASE=PaymentDB;"
        "UID=sa;"
        "PWD=SaPass123!;"
        "TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


def send_notification(n_type: str, message: str):
    try:
        requests.post(
            NOTIFY_URL,
            json={"type": n_type, "message": message},
            timeout=2
        )
    except Exception:
        pass


# ----------------------------------------------------------------------
# Проверка токена через auth_service
# ----------------------------------------------------------------------
def verify_token(header_val: str):
    if not header_val:
        return None
    token = header_val
    if token.startswith("Bearer "):
        token = token.replace("Bearer ", "", 1)

    try:
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get(AUTH_URL, headers=headers, timeout=3)
        data = res.json()
        if res.status_code == 200 and data.get("valid"):
            print(f"[AUTH OK] user = {data.get('user')}")
            return data.get("user")
        print(f"[AUTH FAIL] Response: {data}")
        return None
    except Exception as e:
        print(f"[AUTH ERROR] {e}")
        return None


# ----------------------------------------------------------------------
# POST /payment/pay — создать оплату
# ----------------------------------------------------------------------
@app.route("/payment/pay", methods=["POST"])
def make_payment():
    auth_header = request.headers.get("Authorization", "")
    user = verify_token(auth_header)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    session_id = data.get("session_id")
    method = data.get("method", "Card")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    # забираем инфу о сессии из parking_service
    try:
        r = requests.get(f"{PARKING_URL}/parking/session/{session_id}", timeout=5)
        if r.status_code != 200:
            return jsonify({"error": "Session not found in parking_service"}), 400
        sdata = r.json()
        amount = float(sdata.get("calculated_fee", 0))
    except Exception as e:
        print(f"[PARKING ERROR] {e}")
        return jsonify({"error": "Cannot get session info from parking_service"}), 500

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO Payments (session_id, user_name, amount, method, paid_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, user, amount, method, datetime.datetime.now())
        )
        conn.commit()
        cursor.close()
        conn.close()

        msg = f"Payment {amount} via {method} for session {session_id} by {user}"
        print(f"[PAYMENT] {msg}")
        send_notification("payment", msg)

        return jsonify({
            "message": "Payment recorded",
            "session_id": session_id,
            "amount": amount,
            "method": method
        }), 200
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500


# ----------------------------------------------------------------------
# GET /payment/history — история оплат пользователя
# ----------------------------------------------------------------------
@app.route("/payment/history", methods=["GET"])
def payment_history():
    auth_header = request.headers.get("Authorization", "")
    user = verify_token(auth_header)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT session_id, amount, method, paid_at
            FROM Payments
            WHERE user_name = ?
            ORDER BY paid_at DESC
            """,
            (user,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        history = [
            {
                "session_id": r[0],
                "amount": float(r[1]),
                "method": r[2],
                "paid_at": str(r[3])
            }
            for r in rows
        ]
        return jsonify(history), 200
    except Exception as e:
        print(f"[DB ERROR] {e}")
        return jsonify({"error": "Database error", "details": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004)
