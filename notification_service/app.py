from flask import Flask, request, jsonify
import pyodbc
import datetime

app = Flask(__name__)

def get_conn():
    return pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=host.docker.internal,1433;"
        "DATABASE=NotificationDB;"
        "UID=sa;"
        "PWD=SaPass123!;"
        "TrustServerCertificate=yes;"
    )

# Init DB
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name='Notifications')
        CREATE TABLE Notifications (
            id INT IDENTITY(1,1) PRIMARY KEY,
            type VARCHAR(30) NOT NULL,
            message VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL DEFAULT GETDATE()
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

init_db()

# POST /notify
@app.route("/notify", methods=["POST"])
def notify():
    data = request.get_json() or {}
    n_type = data.get("type", "info")
    message = data.get("message")

    if not message:
        return jsonify({"error": "Missing message"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO Notifications (type, message)
        VALUES (?, ?)
    """, (n_type, message))
    conn.commit()

    cur.close()
    conn.close()

    return jsonify({"status": "saved"})

# GET /notifications
@app.route("/notifications", methods=["GET"])
def list_notifications():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, type, message, created_at FROM Notifications ORDER BY id DESC")
    rows = cur.fetchall()

    result = [{
        "id": r[0],
        "type": r[1],
        "message": r[2],
        "created_at": str(r[3])
    } for r in rows]

    return jsonify(result)

# GET /notifications/recent?limit=20
@app.route("/notifications/recent", methods=["GET"])
def recent():
    limit = int(request.args.get("limit", 20))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT TOP (?) id, type, message, created_at FROM Notifications ORDER BY id DESC",
        (limit,)
    )
    rows = cur.fetchall()

    result = [{
        "id": r[0],
        "type": r[1],
        "message": r[2],
        "created_at": str(r[3])
    } for r in rows]

    return jsonify(result)

# DELETE /notifications/clear
@app.route("/notifications/clear", methods=["DELETE"])
def clear():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM Notifications")
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"status": "cleared"})

@app.route("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5012)
