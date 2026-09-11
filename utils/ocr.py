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


def _ocr(image, config="--oem 3 --psm 6"):
    try:
        return pytesseract.image_to_string(
            image,
            config=config,
            timeout=8
        ).strip()
    except Exception as e:
        print("OCR error:", e)
        return ""


def _prepare(image):
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    gray = cv2.resize(
        gray,
        None,
        fx=2,
        fy=2,
        interpolation=cv2.INTER_CUBIC
    )

    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    return gray


def extract_text(image_path):

    image = cv2.imread(image_path)

    if image is None:
        return ""

    h, w = image.shape[:2]

    # Keep processing size reasonable for Render
    max_width = 1600

    if w > max_width:
        scale = max_width / float(w)

        image = cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA
        )

    gray = _prepare(image)

    results = []

    # --------------------------------
    # 1. Main OCR - product name
    # --------------------------------

    text = _ocr(
        gray,
        "--oem 3 --psm 6"
    )

    if text:
        results.append(text)


    # --------------------------------
    # 2. Second OCR - labels + dates
    # --------------------------------

    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        9
    )

    text2 = _ocr(
        adaptive,
        "--oem 3 --psm 11"
    )

    if text2:
        results.append(text2)


    # --------------------------------
    # 3. Focus on lower package area
    # --------------------------------

    h2 = gray.shape[0]

    start = int(h2 * 0.45)

    lower = gray[start:h2, :]

    if lower.size:

        lower_text = _ocr(
            lower,
            "--oem 3 --psm 11"
        )

        if lower_text:
            results.append(lower_text)


    # --------------------------------
    # 4. Numeric date scan
    # --------------------------------

    numeric = _ocr(
        adaptive,
        "--oem 3 --psm 11 "
        "-c tessedit_char_whitelist=0123456789/.-:"
    )

    if numeric:
        results.append("DATE_SCAN " + numeric)


    # --------------------------------
    # Remove duplicates
    # --------------------------------

    unique = []

    for item in results:

        item = item.strip()

        if item and item not in unique:
            unique.append(item)


    return "\n".join(unique)
