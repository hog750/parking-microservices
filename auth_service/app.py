from flask import Flask, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import pyodbc
import jwt
import datetime
import sys

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecretkey"


# ----------------------------------------------------
# DATABASE
# ----------------------------------------------------
def get_db_connection():
    return pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=host.docker.internal,1433;"
        "DATABASE=AuthDB;"
        "UID=sa;"
        "PWD=SaPass123!;"
        "TrustServerCertificate=yes;"
    )


# ----------------------------------------------------
# SIGNUP  (supports role=admin)
# ----------------------------------------------------
@app.route("/auth/signup", methods=["POST"])
def signup():
    try:
        data = request.get_json() or {}
        username = data.get("username")
        password = data.get("password")
        role = data.get("role", "user")   # <-- ВАЖНО: берём роль из запроса

        if not username or not password:
            return jsonify({"error": "Missing username or password"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # ensure table exists
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Users' AND xtype='U')
            CREATE TABLE Users (
                id INT IDENTITY(1,1) PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'user'
            )
        """)
        conn.commit()

        # check duplicate
        cursor.execute("SELECT id FROM Users WHERE username = ?", (username,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "User already exists"}), 400

        hashed = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO Users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, hashed, role)   # <-- ВСТАВЛЯЕМ РОЛЬ
        )
        conn.commit()

        cursor.close()
        conn.close()

        print(f"[SIGNUP] user={username}, role={role}", file=sys.stderr)
        return jsonify({"message": "User created successfully", "role": role}), 201

    except Exception as e:
        print("[SIGNUP ERROR]", e, file=sys.stderr)
        return jsonify({"error": "Signup failed", "details": str(e)}), 500


# ----------------------------------------------------
# LOGIN (now returns user + role)
# ----------------------------------------------------
@app.route("/auth/login", methods=["POST"])
def login():
    try:
        data = request.get_json() or {}
        username = data.get("username")
        password = data.get("password")

        if not username or not password:
            return jsonify({"error": "Missing credentials"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT password_hash, role FROM Users WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()

        cursor.close()
        conn.close()

        if not row or not check_password_hash(row[0], password):
            return jsonify({"error": "Invalid credentials"}), 401

        role = row[1]

        token = jwt.encode(
            {
                "user": username,
                "role": role,  # <-- роль в токене
                "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=2)
            },
            app.config["SECRET_KEY"],
            algorithm="HS256"
        )

        print(f"[LOGIN SUCCESS] user={username}, role={role}", file=sys.stderr)
        return jsonify({"token": token, "role": role}), 200

    except Exception as e:
        print("[LOGIN ERROR]", e, file=sys.stderr)
        return jsonify({"error": "Login failed", "details": str(e)}), 500


# ----------------------------------------------------
# VERIFY TOKEN (now returns role too)
# ----------------------------------------------------
@app.route("/auth/verify", methods=["GET"])
def verify():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"valid": False, "error": "Missing token"}), 401

    if token.startswith("Bearer "):
        token = token.replace("Bearer ", "", 1)

    try:
        decoded = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        return jsonify({
            "valid": True,
            "user": decoded["user"],
            "role": decoded.get("role", "user")
        }), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"valid": False, "error": "Token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"valid": False, "error": "Invalid token"}), 401


# ----------------------------------------------------
# HEALTH
# ----------------------------------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ----------------------------------------------------
# MAIN
# ----------------------------------------------------
if __name__ == "__main__":
    print("[AUTH SERVICE STARTED] Listening on port 5001", file=sys.stderr)
    app.run(host="0.0.0.0", port=5001)
