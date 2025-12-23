from flask import Flask, request, jsonify
import pyodbc
import datetime

app = Flask(__name__)


# ------------------------------------------------------
# FEE CALCULATION
# ------------------------------------------------------
def calculate_fee(minutes: float, hourly_rate: float, free_minutes: int) -> float:
    """Compute parking fee based on elapsed minutes, free minutes and hourly rate."""
    billable = max(0, minutes - free_minutes)
    fee = (billable / 60.0) * hourly_rate
    return round(fee, 2)


# ------------------------------------------------------
# DATABASE CONNECTION
# ------------------------------------------------------
def get_conn():
    return pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=host.docker.internal,1433;"
        "DATABASE=TariffDB;"
        "UID=sa;PWD=SaPass123!;"
        "TrustServerCertificate=yes;"
    )

# ------------------------------------------------------
# INITIALIZATION — FIX TABLE AND COLUMNS
# ------------------------------------------------------
def init_tariff_table():
    conn = get_conn()
    cur = conn.cursor()

    # Create table if missing
    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name='Tariff')
        CREATE TABLE Tariff (
            id INT IDENTITY(1,1) PRIMARY KEY,
            hourly_rate DECIMAL(10,2) NOT NULL,
            free_minutes INT NOT NULL,
            updated_at DATETIME NOT NULL DEFAULT GETDATE()
        )
    """)
    conn.commit()

    # Ensure "hourly_rate" exists
    cur.execute("""
        IF NOT EXISTS (
            SELECT * FROM sys.columns 
            WHERE Name = N'hourly_rate' AND Object_ID = Object_ID(N'Tariff')
        )
        ALTER TABLE Tariff ADD hourly_rate DECIMAL(10,2) NOT NULL DEFAULT 30;
    """)
    conn.commit()

    # Ensure "free_minutes" exists
    cur.execute("""
        IF NOT EXISTS (
            SELECT * FROM sys.columns 
            WHERE Name = N'free_minutes' AND Object_ID = Object_ID(N'Tariff')
        )
        ALTER TABLE Tariff ADD free_minutes INT NOT NULL DEFAULT 30;
    """)
    conn.commit()

    # If table empty — create default tariff
    cur.execute("SELECT COUNT(*) FROM Tariff")
    count = cur.fetchone()[0]
    if count == 0:
        cur.execute("""
            INSERT INTO Tariff (hourly_rate, free_minutes)
            VALUES (30, 2)
        """)
        conn.commit()

    cur.close()
    conn.close()


init_tariff_table()

# ------------------------------------------------------
# GET CURRENT TARIFF
# ------------------------------------------------------
@app.route("/tariff/current", methods=["GET"])
def current_tariff():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT TOP 1 hourly_rate, free_minutes, updated_at
        FROM Tariff
        ORDER BY updated_at DESC
    """)

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "No tariff defined"}), 404

    return jsonify({
        "hourly_rate": float(row[0]),
        "free_minutes": int(row[1]),
        "updated_at": str(row[2])
    })


# ------------------------------------------------------
# CALCULATE FEE FOR GIVEN MINUTES
# ------------------------------------------------------
@app.route("/tariffs/calc", methods=["GET"])
def calc_tariff():
    minutes_raw = request.args.get("minutes")
    if minutes_raw is None:
        return jsonify({"error": "minutes is required"}), 400

    try:
        minutes_val = float(minutes_raw)
    except ValueError:
        return jsonify({"error": "minutes must be a number"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT TOP 1 hourly_rate, free_minutes FROM Tariff ORDER BY updated_at DESC"
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "No tariff defined"}), 404

    hourly_rate, free_minutes = float(row[0]), int(row[1])
    fee = calculate_fee(minutes_val, hourly_rate, free_minutes)

    return jsonify({
        "minutes": round(minutes_val, 2),
        "free_minutes": free_minutes,
        "hourly_rate": hourly_rate,
        "fee": fee
    })


# ------------------------------------------------------
# UPDATE TARIFF
# ------------------------------------------------------
@app.route("/tariff/update", methods=["POST"])
def update_tariff():
    data = request.get_json() or {}
    hourly = data.get("hourly_rate")
    free = data.get("free_minutes")

    if hourly is None or free is None:
        return jsonify({"error": "Missing hourly_rate or free_minutes"}), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO Tariff (hourly_rate, free_minutes, updated_at)
        VALUES (?, ?, GETDATE())
    """, (float(hourly), int(free)))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "message": "Tariff updated",
        "hourly_rate": hourly,
        "free_minutes": free
    })


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    # Port aligned with docker-compose (5011)
    app.run(host="0.0.0.0", port=5011)
