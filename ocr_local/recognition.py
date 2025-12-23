import easyocr
import cv2
import re
import numpy as np
import sys
import os

class LicensePlateRecognizer:
    def __init__(self):
        try:
            self.ocr = easyocr.Reader(['en'], gpu=False)
            # print("EasyOCR initialized successfully")
        except Exception as e:
            print(f"Error initializing EasyOCR: {e}")
            raise

    def preprocess_image(self, img):
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray = cv2.bilateralFilter(gray, 11, 17, 17)  # шумоподавление
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return binary
        except Exception:
            return None

    def detect_and_read_plate(self, image_path):
        try:
            img = cv2.imread(image_path)
            if img is None:
                print("ERROR: Cannot read image")
                return ""

            processed_img = self.preprocess_image(img)
            if processed_img is None:
                print("ERROR: Preprocess failed")
                return ""

            results = self.ocr.readtext(processed_img)
            # print("Raw OCR:", results)

            if not results:
                return ""

            texts = [text.upper() for (_, text, conf) in results if conf > 0.05]
            cleaned = [re.sub(r'[^A-Z0-9]', '', t) for t in texts if t.strip()]

            # формируем похожие на номера комбинации
            candidates = set()
            for i in range(len(cleaned)):
                candidates.add(cleaned[i])
                if i + 1 < len(cleaned):
                    candidates.add(cleaned[i] + cleaned[i+1])

            # паттерн: буквы + цифры
            plate_pattern = re.compile(r"^[A-Z]{2,4}[0-9]{2,4}$")

            for c in candidates:
                if plate_pattern.fullmatch(c):
                    return c

            return ""
        except Exception:
            return ""


# ===================================================================
# Теперь делаем CLI-режим (как нужно для вызова через subprocess)
# ===================================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("ERROR: No image path provided")
        sys.exit(1)

    image_path = sys.argv[1]

    if not os.path.exists(image_path):
        print("ERROR: File does not exist")
        sys.exit(1)

    recognizer = LicensePlateRecognizer()
    plate = recognizer.detect_and_read_plate(image_path)

    print(plate if plate else "")
