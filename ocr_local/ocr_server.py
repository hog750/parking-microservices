from flask import Flask, request, jsonify
import subprocess
import tempfile
import os

app = Flask(__name__)

# путь к твоему Python.exe с EasyOCR
PYTHON_PATH = r"C:\Users\hog750\Desktop\parking-microservices\ocr_env\Scripts\python.exe"

@app.route("/recognize", methods=["POST"])
def recognize():
    if "image" not in request.files:
        return jsonify({"error": "no image"}), 400

    img = request.files["image"]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
        img.save(f.name)
        path = f.name

    try:
        out = subprocess.check_output(
            [PYTHON_PATH, "recognition.py", path],
            text=True
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        os.unlink(path)

    return jsonify({"plate": out.strip()})

@app.route("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010)
