import os
import requests
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    Response,
    abort,
)

app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET_KEY", "dashboardsecret")

# ------- Service base URLs (set via docker-compose) -------
AUTH_URL = os.getenv("AUTH_URL_BASE", "http://auth_service:5001")
PARKING_URL = os.getenv("PARKING_URL_BASE", "http://parking_service:5003")
PAYMENT_URL = os.getenv("PAYMENT_URL_BASE", "http://payment_service:5004")
VEHICLE_URL = os.getenv("VEHICLE_URL_BASE", "http://vehicle_service:5002")
ANALYTICS_URL = os.getenv("ANALYTICS_URL_BASE", "http://analytics_service:5005")
MONITOR_URL = os.getenv("MONITOR_URL_BASE", "http://monitoring_service:5006")
TARIFF_URL = os.getenv("TARIFF_URL_BASE", "http://tariff_service:5011")
OFFLINE_URL = os.getenv("OFFLINE_URL_BASE", "http://offline_payment_service:5008")
NOTIFICATION_URL = os.getenv("NOTIFICATION_URL_BASE", "http://notification_service:5012")

# OCR service (venv + EasyOCR)
OCR_URL = os.getenv("OCR_URL_BASE", "http://host.docker.internal:5010")


# ======================================================
#  Auth token verification helper
# ======================================================
def verify_token():
    """
    Validate JWT via auth_service.
    Returns (ok: bool, role: str|None, username: str|None)
    """
    token = session.get("token")
    if not token:
        return False, None, None

    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{AUTH_URL}/auth/verify", headers=headers, timeout=5)
        if r.status_code != 200:
            return False, None, None
        data = r.json()
        if not data.get("valid"):
            return False, None, None
        username = data.get("user")
        role = data.get("role", "user")
        return True, role, username
    except Exception:
        return False, None, None


# ======================================================
#  HOME
# ======================================================
@app.route("/")
def home():
    ok, role, username = verify_token()
    return render_template(
        "index.html",
        logged_in=ok,
        role=role,
        username=username,
    )


# ======================================================
#  AUTH: LOGIN / SIGNUP / LOGOUT
# ======================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Username and password are required", "danger")
            return render_template("login.html")

        try:
            res = requests.post(
                f"{AUTH_URL}/auth/login",
                json={"username": username, "password": password},
                timeout=5,
            )
        except Exception as e:
            flash(f"Auth service unavailable: {e}", "danger")
            return render_template("login.html")

        if res.status_code != 200:
            msg = res.json().get("error", "Invalid credentials")
            flash(msg, "danger")
            return render_template("login.html")

        body = res.json()
        token = body.get("token")
        if not token:
            flash("Auth service did not return token", "danger")
            return render_template("login.html")

        session["token"] = token
        ok, role, uname = verify_token()
        session["role"] = role or "user"
        session["username"] = uname or username

        flash("Login successful", "success")
        if role == "admin":
            return redirect(url_for("dashboard"))
        else:
            return redirect(url_for("user_panel"))

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Username and password are required", "danger")
            return render_template("signup.html")

        try:
            res = requests.post(
                f"{AUTH_URL}/auth/signup",
                json={"username": username, "password": password},
                timeout=5,
            )
        except Exception as e:
            flash(f"Auth service unavailable: {e}", "danger")
            return render_template("signup.html")

        if res.status_code == 201:
            flash("Account created. You can now log in.", "success")
            return redirect(url_for("login"))
        else:
            msg = res.json().get("error", "Signup failed")
            flash(msg, "danger")

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for("home"))


# ======================================================
#  ADMIN DASHBOARD
# ======================================================
@app.route("/dashboard")
def dashboard():
    ok, role, username = verify_token()
    if not ok:
        session.clear()
        flash("Please log in first", "danger")
        return redirect(url_for("login"))

    if role != "admin":
        return render_template(
            "access_denied.html",
            logged_in=ok,
            role=role,
            username=username,
        )

    token = session.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # --- Analytics ---
    stats = {
        "today_revenue": 0,
        "today_sessions": 0,
        "avg_parking_minutes": 0,
        "occupied_slots": 0,
        "free_slots": 0,
        "unique_vehicles": 0,
    }
    try:
        r = requests.get(f"{ANALYTICS_URL}/analytics/summary", headers=headers, timeout=5)
        if r.status_code == 200:
            stats.update(r.json())
    except Exception as e:
        flash(f"Analytics error: {e}", "warning")

    # --- Monitoring ---
    health = {}
    try:
        h = requests.get(f"{MONITOR_URL}/monitor/health", timeout=5)
        if h.status_code == 200:
            health = h.json()
    except Exception as e:
        flash(f"Monitoring error: {e}", "warning")

    # --- Tariff (optional) ---
    tariff = None
    try:
        t = requests.get(f"{TARIFF_URL}/tariff/current", timeout=3)
        if t.status_code == 200:
            tariff = t.json()
    except Exception:
        pass

    # --- Active sessions ---
    active_sessions = []
    try:
        r = requests.get(f"{PARKING_URL}/parking/active_sessions", headers=headers, timeout=5)
        if r.status_code == 200:
            active_sessions = r.json()
    except Exception as e:
        flash(f"Parking sessions error: {e}", "warning")

    # --- Notifications ---
    notifications = []
    try:
        r = requests.get(
            f"{NOTIFICATION_URL}/notifications/recent",
            params={"limit": 20},
            timeout=5,
        )
        if r.status_code == 200:
            notifications = r.json()
    except Exception as e:
        flash(f"Notification service error: {e}", "warning")

    return render_template(
        "dashboard.html",
        stats=stats,
        health=health,
        tariff=tariff,
        active_sessions=active_sessions,
        notifications=notifications,
        logged_in=ok,
        role=role,
        username=username,
    )


# ======================================================
#  USER PANEL
# ======================================================
@app.route("/user")
def user_panel():
    ok, role, username = verify_token()
    if not ok:
        session.clear()
        flash("Please log in first", "danger")
        return redirect(url_for("login"))
    if role == "admin":
        return redirect(url_for("dashboard"))

    return render_template(
        "user_dashboard.html",
        logged_in=ok,
        role=role,
        username=username,
    )


# ======================================================
#  USER: Upload car plate (OCR)
#   endpoint name matches user_upload_plate (used in base.html)
# ======================================================
@app.route("/user/upload-plate", methods=["GET", "POST"])
def user_upload_plate():
    ok, role, username = verify_token()
    if not ok:
        session.clear()
        flash("Please log in first", "danger")
        return redirect(url_for("login"))
    if role == "admin":
        return redirect(url_for("dashboard"))

    token = session.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    detected_plate = None

    if request.method == "POST":
        if "image" not in request.files or request.files["image"].filename == "":
            flash("Please choose an image file", "danger")
            return render_template(
                "user_ocr.html",
                detected_plate=None,
                logged_in=ok,
                role=role,
                username=username,
            )

        img = request.files["image"]

        # 1) Send image to OCR service
        try:
            ocr_res = requests.post(
                f"{OCR_URL}/recognize",
                files={"image": (img.filename, img.stream, img.mimetype)},
                timeout=30,
            )
            if ocr_res.status_code != 200:
                flash("OCR service error", "danger")
            else:
                data = ocr_res.json()
                detected_plate = (data.get("plate") or "").strip().upper()
                if not detected_plate:
                    flash("Could not recognize plate", "warning")
        except Exception as e:
            flash(f"OCR service unavailable: {e}", "danger")

        # 2) Register vehicle in vehicle_service
        if detected_plate:
            try:
                v_res = requests.post(
                    f"{VEHICLE_URL}/vehicle/add",
                    json={"license_plate": detected_plate},
                    headers=headers,
                    timeout=5,
                )
                if v_res.status_code == 200:
                    flash(f"Vehicle {detected_plate} registered", "success")
                else:
                    msg = v_res.json().get("error", "Vehicle registration failed")
                    flash(msg, "danger")
            except Exception as e:
                flash(f"Vehicle service error: {e}", "danger")

    return render_template(
        "user_ocr.html",
        detected_plate=detected_plate,
        logged_in=ok,
        role=role,
        username=username,
    )


# ======================================================
#  USER: Choose parking spot (user_slots)
# ======================================================
@app.route("/user/slots", methods=["GET", "POST"])
def user_slots():
    ok, role, username = verify_token()
    if not ok:
        session.clear()
        flash("Please log in first", "danger")
        return redirect(url_for("login"))
    if role == "admin":
        return redirect(url_for("dashboard"))

    token = session.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    last_session_id = None
    offline_qr_code = None

    if request.method == "POST":
        slot_id = request.form.get("slot_id")
        if not slot_id:
            flash("Slot ID is required", "danger")
        else:
            try:
                payload = {"slot_id": int(slot_id)}
                r = requests.post(
                    f"{PARKING_URL}/parking/start",
                    json=payload,
                    headers=headers,
                    timeout=5,
                )
                if r.status_code == 200:
                    res_data = r.json()
                    msg = res_data.get("message", "Parking started")
                    last_session_id = res_data.get("session_id")
                    # try to prepare offline QR right away (amount may be 0, real fee will be set at payment time)
                    if last_session_id:
                        try:
                            qr_res = requests.post(
                                f"{OFFLINE_URL}/offline/init",
                                json={"session_id": last_session_id, "amount": 0},
                                timeout=5,
                            )
                            if qr_res.status_code in (200, 201):
                                offline_qr_code = qr_res.json().get("qr_code")
                        except Exception:
                            pass
                    flash(msg, "success")
                else:
                    msg = r.json().get("error", "Failed to start parking")
                    flash(msg, "danger")
            except Exception as e:
                flash(f"Parking service error: {e}", "danger")

    # Load slots list
    slots = []
    try:
        r = requests.get(f"{PARKING_URL}/parking/slots", timeout=5)
        if r.status_code == 200:
            slots = r.json()
    except Exception as e:
        flash(f"Parking service error: {e}", "danger")

    return render_template(
        "user_slots.html",
        slots=slots,
        last_session_id=last_session_id,
        offline_qr_code=offline_qr_code,
        logged_in=ok,
        role=role,
        username=username,
    )


# ======================================================
#  USER: Stop parking + offline QR
# ======================================================
@app.route("/user/stop", methods=["GET", "POST"])
def user_stop():
    ok, role, username = verify_token()
    if not ok:
        session.clear()
        flash("Please log in first", "danger")
        return redirect(url_for("login"))
    if role == "admin":
        return redirect(url_for("dashboard"))

    token = session.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    result = None
    qr_code = None

    if request.method == "POST":
        # 1) Stop current session
        try:
            r = requests.post(f"{PARKING_URL}/parking/stop", headers=headers, timeout=5)
        except Exception as e:
            flash(f"Parking service error: {e}", "danger")
            return render_template(
                "user_stop.html",
                result=None,
                qr_code=None,
                logged_in=ok,
                role=role,
                username=username,
            )

        if r.status_code != 200:
            msg = r.json().get("error", "Failed to stop parking")
            flash(msg, "danger")
            return render_template(
                "user_stop.html",
                result=None,
                qr_code=None,
                logged_in=ok,
                role=role,
                username=username,
            )

        result = r.json()
        fee = float(result.get("fee", 0))
        session_id = result.get("session_id")

        # 2) If fee > 0, create offline QR in offline service
        if fee > 0 and session_id:
            try:
                qr_res = requests.post(
                    f"{OFFLINE_URL}/offline/init",
                    json={"session_id": session_id, "amount": fee},
                    timeout=5,
                )
                if qr_res.status_code in (200, 201):
                    qr_code = qr_res.json().get("qr_code")
                    flash("Parking stopped. Offline QR created.", "success")
                else:
                    flash("Parking stopped, but offline QR creation failed", "warning")
            except Exception as e:
                flash(f"Offline service error: {e}", "warning")
        else:
            flash("Parking stopped. No payment required.", "success")

    return render_template(
        "user_stop.html",
        result=result,
        qr_code=qr_code,
        logged_in=ok,
        role=role,
        username=username,
    )


# PROXY for offline QR images
@app.route("/offline/qr/<code>")
def offline_qr(code):
    try:
        r = requests.get(f"{OFFLINE_URL}/offline/qr/{code}", timeout=5)
        if r.status_code != 200:
            abort(404)
        return Response(
            r.content,
            content_type=r.headers.get("Content-Type", "image/png"),
        )
    except Exception:
        abort(404)


# ======================================================
#  USER: Payment history
# ======================================================
@app.route("/user/history")
def user_history():
    ok, role, username = verify_token()
    if not ok:
        session.clear()
        flash("Please log in first", "danger")
        return redirect(url_for("login"))
    if role == "admin":
        return redirect(url_for("dashboard"))

    token = session.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    payments = []
    try:
        r = requests.get(f"{PAYMENT_URL}/payment/history", headers=headers, timeout=5)
        if r.status_code == 200:
            payments = r.json()
    except Exception as e:
        flash(f"Payment service error: {e}", "danger")

    return render_template(
        "user_history.html",
        payments=payments,
        logged_in=ok,
        role=role,
        username=username,
    )


# ======================================================
#  ONLINE PAY (/pay)
# ======================================================
@app.route("/pay", methods=["GET", "POST"])
def pay():
    ok, role, username = verify_token()
    if not ok:
        flash("Please log in first", "danger")
        return redirect(url_for("login"))

    token = session.get("token")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    # Tariff info (optional)
    tariff = None
    try:
        t = requests.get(f"{TARIFF_URL}/tariff/current", timeout=3)
        if t.status_code == 200:
            tariff = t.json()
    except Exception:
        pass

    # Pre-fill last finished session for convenience
    last_session_id = None
    last_amount = None
    payment_result = None

    try:
        r = requests.get(
            f"{PARKING_URL}/parking/my_last_session",
            headers=headers,
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            last_session_id = data.get("session_id")
            last_amount = data.get("calculated_fee")
    except Exception as e:
        flash(f"Parking service error: {e}", "warning")

    if request.method == "POST":
        session_id = request.form.get("session_id", "").strip() or last_session_id
        method = request.form.get("method", "Card")

        if not session_id:
            flash("No finished session to pay for", "danger")
            return render_template(
                "pay.html",
                tariff=tariff,
                last_session_id=last_session_id,
                last_amount=last_amount,
                payment_result=payment_result,
                logged_in=ok,
                role=role,
                username=username,
            )

        payload = {
            "session_id": session_id,
            "method": method,
        }

        try:
            r = requests.post(
                f"{PAYMENT_URL}/payment/pay",
                json=payload,
                headers=headers,
                timeout=5,
            )
            if r.status_code == 200:
                payment_result = r.json()
                flash("Payment successful", "success")
            else:
                msg = r.json().get("error", "Payment failed")
                flash(msg, "danger")
        except Exception as e:
            flash(f"Payment service unavailable: {e}", "danger")

    return render_template(
        "pay.html",
        tariff=tariff,
        last_session_id=last_session_id,
        last_amount=last_amount,
        payment_result=payment_result,
        logged_in=ok,
        role=role,
        username=username,
    )


# ======================================================
#  OFFLINE PAY PAGE (by QR text)
# ======================================================
@app.route("/offline/pay", methods=["GET", "POST"])
def offline_pay():
    ok, role, username = verify_token()
    if not ok:
        flash("Please log in first", "danger")
        return redirect(url_for("login"))

    result = None

    if request.method == "POST":
        qr_code = request.form.get("qr_code", "").strip()
        if not qr_code:
            flash("QR code is required", "danger")
        else:
            try:
                r = requests.post(
                    f"{OFFLINE_URL}/offline/pay",
                    json={"qr_code": qr_code},
                    timeout=5,
                )
                if r.status_code == 200:
                    result = r.json()
                    flash("Offline payment successful", "success")
                else:
                    msg = r.json().get("error", "Offline payment failed")
                    flash(msg, "danger")
            except Exception as e:
                flash(f"Offline service error: {e}", "danger")

    return render_template(
        "offline_pay.html",
        result=result,
        logged_in=ok,
        role=role,
        username=username,
    )


# ======================================================
#  HEALTH
# ======================================================
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
