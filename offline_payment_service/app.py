from flask import Flask, request, jsonify, send_file
import pyodbc
import datetime
import uuid
import io
import qrcode
import os
import requests

app = Flask(__name__)
PARKING_URL = os.getenv("PARKING_URL_BASE", "http://parking_service:5003")

# ------------------ DB CONNECTION ------------------
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


# ------------------ INIT DB ------------------
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # OfflinePayments
    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name='OfflinePayments')
        CREATE TABLE OfflinePayments (
            id INT IDENTITY(1,1) PRIMARY KEY,
            session_id VARCHAR(50) NOT NULL,
            amount DECIMAL(10,2) NOT NULL,
            qr_code VARCHAR(100) NOT NULL UNIQUE,
            is_paid BIT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT GETDATE(),
            paid_at DATETIME NULL
        )
    """)

    # Payments (на всякий случай)
    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name='Payments')
        CREATE TABLE Payments (
            id INT IDENTITY(1,1) PRIMARY KEY,
            session_id VARCHAR(50) NOT NULL,
            user_name VARCHAR(50) NULL,
            amount DECIMAL(10,2) NOT NULL,
            method VARCHAR(20) NOT NULL,
            paid_at DATETIME NOT NULL
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


init_db()


# ------------------ HEALTH ------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ------------------ /offline/init ------------------
@app.route("/offline/init", methods=["POST"])
def offline_init():
    """
    Создать офлайн-счёт. 
    Возвращает session_id, amount, qr_code.
    """
    data = request.get_json() or {}
    session_id = data.get("session_id")
    amount = data.get("amount", 0)

    if not session_id or amount is None:
        return jsonify({"error": "Missing session_id or amount"}), 400

    try:
        amount = float(amount)
        if amount < 0:
            return jsonify({"error": "Amount must be non-negative"}), 400
    except Exception:
        return jsonify({"error": "Invalid amount"}), 400

    qr_code = f"OFF-{uuid.uuid4()}"

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO OfflinePayments (session_id, amount, qr_code, is_paid)
            VALUES (?, ?, ?, 0)
        """, (session_id, amount, qr_code))

        conn.commit()
        return jsonify({
            "message": "Offline payment created",
            "session_id": session_id,
            "amount": amount,
            "qr_code": qr_code
        }), 201

    except Exception as e:
        return jsonify({"error": "Database error", "details": str(e)}), 500

    finally:
        cur.close()
        conn.close()


# ------------------ /offline/qr/<qr_code> ------------------
@app.route("/offline/qr/<qr_code>", methods=["GET"])
def get_qr_image(qr_code):
    """
    Возвращает PNG-картинку QR-кода.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM OfflinePayments WHERE qr_code = ?", (qr_code,))
        exists = cur.fetchone()[0] > 0

        cur.close()
        conn.close()

        if not exists:
            return jsonify({"error": "QR not found"}), 404

        img = qrcode.make(qr_code)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        return send_file(buf, mimetype="image/png")

    except Exception as e:
        return jsonify({"error": "QR generation error", "details": str(e)}), 500


# ------------------ /offline/pay ------------------
@app.route("/offline/pay", methods=["POST"])
def offline_pay():
    """
    Использовать QR для оплаты.
    """
    data = request.get_json() or {}
    qr_code = data.get("qr_code")

    if not qr_code:
        return jsonify({"error": "Missing qr_code"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id, session_id, amount, is_paid
            FROM OfflinePayments
            WHERE qr_code = ?
        """, (qr_code,))
        row = cur.fetchone()

        if not row:
            return jsonify({"error": "QR not found"}), 404

        offline_id, session_id, amount, is_paid = row

        if is_paid:
            return jsonify({
                "message": "Already paid",
                "session_id": session_id,
                "amount": float(amount)
            }), 200

        # If amount is zero or missing, fetch current fee from parking_service
        if amount is None or float(amount) == 0:
            try:
                s_res = requests.get(f"{PARKING_URL}/parking/session/{session_id}", timeout=5)
                if s_res.status_code == 200:
                    sdata = s_res.json()
                    amount = float(sdata.get("calculated_fee", 0))
                else:
                    amount = 0
            except Exception:
                amount = 0

        # mark as paid
        cur.execute("""
            UPDATE OfflinePayments
            SET is_paid = 1, paid_at = GETDATE(), amount = ?
            WHERE id = ?
        """, (amount, offline_id))

        # also save in Payments
        cur.execute("""
            INSERT INTO Payments (session_id, user_name, amount, method, paid_at)
            VALUES (?, ?, ?, 'Offline', GETDATE())
        """, (session_id, "offline_kiosk", amount))

        conn.commit()

        return jsonify({
            "message": "Offline payment successful",
            "session_id": session_id,
            "amount": float(amount)
        }), 200

    except Exception as e:
        return jsonify({"error": "Database error", "details": str(e)}), 500

    finally:
        cur.close()
        conn.close()


# ------------------ MAIN ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5008)
