from flask import Flask, jsonify
import requests

app = Flask(__name__)

SERVICES = {
    "auth_service":      "http://auth_service:5001/health",
    "vehicle_service":   "http://vehicle_service:5002/health",
    "parking_service":   "http://parking_service:5003/health",
    "payment_service":   "http://payment_service:5004/health",
    "analytics_service": "http://analytics_service:5005/health",
    "dashboard_service": "http://dashboard_service:8080/health"
}

@app.route("/monitor/health", methods=["GET"])
def health_check():
    results = {}
    all_ok = True

    for name, url in SERVICES.items():
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                results[name] = "ok"
            else:
                results[name] = f"error ({r.status_code})"
                all_ok = False
        except Exception as e:
            results[name] = "down"
            all_ok = False

    results["overall"] = "healthy" if all_ok else "issues_detected"
    return jsonify(results), 200


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5006)
