import os
import re
import cv2
import pytesseract

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

LABEL_WORDS = re.compile(
    r"MFG|MFD|EXP|EXPIRY|BEST|BEFORE|USE|BY|MANUFACTUR",
    re.I
)


def _ocr(image, config, timeout=8):
    try:
        return pytesseract.image_to_string(
            image,
            config=config,
            timeout=timeout
        ).strip()
    except Exception as e:
        print("OCR error:", e)
        return ""


def _prepare(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8)
    ).apply(gray)

    return gray, clahe


def extract_text(image_path):
    image = cv2.imread(image_path)

    if image is None:
        return ""

    h, w = image.shape[:2]

    # Keep image size reasonable for Render CPU
    target_w = min(max(w, 1200), 1600)

    scale = target_w / float(w)

    if scale != 1:
        image = cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA
        )

    results = []

    # -------------------------------------------------
    # PASS 1: Whole image - product name + labels
    # -------------------------------------------------
    gray, clahe = _prepare(image)

    text = _ocr(
        clahe,
        "--oem 3 --psm 11",
        timeout=8
    )

    if text:
        results.append(text)

    # -------------------------------------------------
    # PASS 2: Lower package area - dates
    # -------------------------------------------------
    h = image.shape[0]

    date_zone = image[int(h * 0.45):int(h * 0.90), :]

    if date_zone.size:
        date_gray = cv2.cvtColor(
            date_zone,
            cv2.COLOR_BGR2GRAY
        )

        date_gray = cv2.resize(
            date_gray,
            None,
            fx=1.4,
            fy=1.4,
            interpolation=cv2.INTER_CUBIC
        )

        date_bw = cv2.adaptiveThreshold(
            date_gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            9
        )

        date_text = _ocr(
            date_bw,
            "--oem 3 --psm 11",
            timeout=8
        )

        if date_text:
            results.append(date_text)

    # -------------------------------------------------
    # PASS 3: Numeric-only date detection
    # -------------------------------------------------
    numeric_zone = image[int(h * 0.50):int(h * 0.85), :]

    if numeric_zone.size:
        numeric_gray = cv2.cvtColor(
            numeric_zone,
            cv2.COLOR_BGR2GRAY
        )

        numeric_gray = cv2.resize(
            numeric_gray,
            None,
            fx=1.5,
            fy=1.5,
            interpolation=cv2.INTER_CUBIC
        )

        numeric_bw = cv2.threshold(
            numeric_gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )[1]

        numeric_text = _ocr(
            numeric_bw,
            "--oem 3 --psm 6 "
            "-c tessedit_char_whitelist=0123456789/.-",
            timeout=8
        )

        if numeric_text:
            results.append("DATE_SCAN " + numeric_text)

    # -------------------------------------------------
    # Remove duplicate OCR results
    # -------------------------------------------------
    unique = []

    for item in results:
        item = item.strip()

        if item and item not in unique:
            unique.append(item)

    return "\n".join(unique)
