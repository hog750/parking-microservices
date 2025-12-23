from flask import Flask, jsonify, request
import pyodbc
import requests
import datetime

app = Flask(__name__)

AUTH_URL = "http://auth_service:5001/auth/verify"


# =====================================================
#   DATABASE CONNECTIONS
# =====================================================
def get_conn(db_name):
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER=host.docker.internal,1433;"
        f"DATABASE={db_name};"
        f"UID=sa;PWD=SaPass123!;"
        f"TrustServerCertificate=yes;"
    )


# =====================================================
#   TOKEN VERIFICATION (ADMIN ONLY)
# =====================================================
def verify_admin(token):
    if not token:
        return None

    try:
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get(AUTH_URL, headers=headers, timeout=5)
        data = res.json()

        if res.status_code == 200 and data.get("valid"):
            user = data.get("user")
            role = data.get("role", "user")

            # 🔥 теперь аналитика доступна ТОЛЬКО админу
            if role == "admin":
                return user
        return None

    except Exception as e:
        print("[AUTH ERROR]", e)
        return None


# =====================================================
#   SAFE SQL EXECUTION WRAPPER
# =====================================================
def execute_query(db_name, query, params=None, fetchone=False):
    try:
        conn = get_conn(db_name)
        cursor = conn.cursor()

        cursor.execute(query, params or ())
        if fetchone:
            data = cursor.fetchone()
        else:
            data = cursor.fetchall()

        cursor.close()
        conn.close()
        return data

    except Exception as e:
        print("[DB ERROR]", e)
        return None


# =====================================================
#   SUMMARY ANALYTICS
# =====================================================
@app.route("/analytics/summary", methods=["GET"])
def summary():
    token = request.headers.get("Authorization", "").replace("Bearer ", "", 1)
    admin = verify_admin(token)
    if not admin:
        return jsonify({"error": "Admin access required"}), 403

    result = {}

    # === Payments today ===
    row = execute_query(
        "PaymentDB",
        """
        SELECT ISNULL(SUM(amount), 0)
        FROM Payments
        WHERE CAST(paid_at AS DATE) = CAST(GETDATE() AS DATE)
        """,
        fetchone=True
    )
    result["today_revenue"] = float(row[0]) if row else 0

    # === Sessions today ===
    row = execute_query(
        "ParkingDB2",
        """
        SELECT COUNT(*)
        FROM Sessions
        WHERE CAST(entry_time AS DATE) = CAST(GETDATE() AS DATE)
        """,
        fetchone=True
    )
    result["today_sessions"] = row[0] if row else 0

    # === Average duration ===
    row = execute_query(
        "ParkingDB2",
        """
        SELECT AVG(DATEDIFF(MINUTE, entry_time, exit_time))
        FROM Sessions
        WHERE exit_time IS NOT NULL
        """,
        fetchone=True
    )
    result["avg_parking_minutes"] = float(row[0]) if row and row[0] else 0

    # === Slot overview ===
    row = execute_query(
        "ParkingDB2",
        """
        SELECT
            SUM(CASE WHEN status='Occupied' THEN 1 ELSE 0 END) AS occupied,
            SUM(CASE WHEN status='Available' THEN 1 ELSE 0 END) AS free
        FROM ParkingSlots
        """,
        fetchone=True
    )
    result["occupied_slots"] = row[0] if row else 0
    result["free_slots"] = row[1] if row else 0

    # === Unique vehicles ===
    row = execute_query(
        "VehicleDB",
        "SELECT COUNT(DISTINCT license_plate) FROM Vehicles",
        fetchone=True
    )
    result["unique_vehicles"] = row[0] if row else 0

    return jsonify(result), 200


# =====================================================
#   WEEKLY REVENUE ANALYTICS
# =====================================================
@app.route("/analytics/weekly", methods=["GET"])
def weekly_revenue():
    token = request.headers.get("Authorization", "").replace("Bearer ", "", 1)
    admin = verify_admin(token)
    if not admin:
        return jsonify({"error": "Admin access required"}), 403

    rows = execute_query(
        "PaymentDB",
        """
        SELECT CONVERT(date, paid_at) AS day, SUM(amount)
        FROM Payments
        WHERE paid_at >= DATEADD(day, -7, GETDATE())
        GROUP BY CONVERT(date, paid_at)
        ORDER BY day ASC
        """
    )

    data = [{"date": str(r[0]), "revenue": float(r[1])} for r in rows] if rows else []

    return jsonify(data), 200


# =====================================================
#   HOURLY PARKING ACTIVITY (TODAY)
# =====================================================
@app.route("/analytics/hourly", methods=["GET"])
def hourly_activity():
    token = request.headers.get("Authorization", "").replace("Bearer ", "", 1)
    admin = verify_admin(token)
    if not admin:
        return jsonify({"error": "Admin access required"}), 403

    rows = execute_query(
        "ParkingDB2",
        """
        SELECT DATEPART(HOUR, entry_time) AS hour, COUNT(*)
        FROM Sessions
        WHERE CAST(entry_time AS DATE) = CAST(GETDATE() AS DATE)
        GROUP BY DATEPART(HOUR, entry_time)
        ORDER BY hour
        """
    )

    data = [{"hour": int(r[0]), "count": int(r[1])} for r in rows] if rows else []

    return jsonify(data), 200


# =====================================================
#   TOTAL STATS (ALL TIME)
# =====================================================
@app.route("/analytics/total", methods=["GET"])
def totals():
    token = request.headers.get("Authorization", "").replace("Bearer ", "", 1)
    admin = verify_admin(token)
    if not admin:
        return jsonify({"error": "Admin access required"}), 403

    result = {}

    # Total revenue
    row = execute_query(
        "PaymentDB",
        "SELECT ISNULL(SUM(amount), 0) FROM Payments",
        fetchone=True
    )
    result["total_revenue"] = float(row[0])

    # Total sessions
    row = execute_query(
        "ParkingDB2",
        "SELECT COUNT(*) FROM Sessions",
        fetchone=True
    )
    result["total_sessions"] = row[0]

    # Total vehicles
    row = execute_query(
        "VehicleDB",
        "SELECT COUNT(*) FROM Vehicles",
        fetchone=True
    )
    result["total_vehicles"] = row[0]

    return jsonify(result), 200


# =====================================================
#   HEALTH
# =====================================================
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


# =====================================================
#   MAIN
# =====================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005)
