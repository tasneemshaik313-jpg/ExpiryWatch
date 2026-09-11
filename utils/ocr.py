import os
import re
import cv2
import pytesseract

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

LABEL_WORDS = re.compile(r"MFG|MFD|EXP|EXPIRY|BEST|BEFORE|USE|BY|MANUFACTUR", re.I)


def _ocr(image, config):
    try:
        return pytesseract.image_to_string(image, config=config, timeout=12).strip()
    except Exception as e:
        print("OCR error:", e)
        return ""


def _prep_variants(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    # Preserve tiny printed characters while making the background flatter.
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8)).apply(gray)
    denoise = cv2.fastNlMeansDenoising(clahe, None, 7, 7, 21)
    sharp = cv2.addWeighted(denoise, 1.7, cv2.GaussianBlur(denoise, (0, 0), 1.2), -0.7, 0)
    bw = cv2.adaptiveThreshold(sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY, 31, 9)
    return gray, clahe, bw


def _targeted_date_crops(image):
    """Locate label rows and run a tiny-text numeric OCR pass around them."""
    h, w = image.shape[:2]
    y0 = int(h * 0.42)
    lower = image[y0:, :]
    scale = min(2.8, max(1.8, 2400 / max(lower.shape[1], 1)))
    enlarged = cv2.resize(lower, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray, clahe, bw = _prep_variants(enlarged)

    results = []
    label_boxes = []
    try:
        data = pytesseract.image_to_data(
            clahe, config="--oem 3 --psm 11",
            output_type=pytesseract.Output.DICT, timeout=12
        )
        for i, raw in enumerate(data.get("text", [])):
            word = (raw or "").strip()
            if word and LABEL_WORDS.search(word):
                label_boxes.append((int(data["left"][i]), int(data["top"][i]),
                                    int(data["width"][i]), int(data["height"][i]), word))
    except Exception as e:
        print("OCR data error:", e)

    # For each detected MFG/EXP/BEST/BEFORE label, read the same row and the
    # row immediately below it with a numeric whitelist. This is the key step
    # that makes small stamped dates much easier to recognize.
    focused = []

    # Extra MFG-row pass: a slightly smaller 1.5x adaptive image often preserves
    # tiny stamped expiry text better than aggressive enlargement.
    for x, y, ww, hh, word in label_boxes:
        if re.search(r"MFG|MFD|MIG", word, re.I):
            x1 = max(0, x - 120)
            x2 = min(enlarged.shape[1], x + 1050)
            y1 = max(0, y - 30)
            y2 = min(enlarged.shape[0], y + 330)
            stamp = enlarged[y1:y2, x1:x2]
            stamp = cv2.resize(stamp, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
            sg = cv2.cvtColor(stamp, cv2.COLOR_BGR2GRAY)
            sa = cv2.adaptiveThreshold(sg, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 41, 11)
            stamp_text = _ocr(sa, "--oem 3 --psm 11")
            if stamp_text:
                results.append(stamp_text)
    for x, y, ww, hh, word in label_boxes[:8]:
        row_h = max(hh * 7, 120)
        x1 = max(0, x - int(0.08 * enlarged.shape[1]))
        x2 = min(enlarged.shape[1], x + max(ww * 13, int(0.78 * enlarged.shape[1])))
        y1 = max(0, y - hh * 2)
        y2 = min(enlarged.shape[0], y + row_h * 2)
        focused.append((enlarged[y1:y2, x1:x2], word))

    # Fallback numeric bands cover labels that Tesseract failed to recognize.
    # They are deliberately limited to the lower package area where lot/MFG/EXP
    # stamps are commonly printed. Numeric-only OCR is much better at tiny stamps.
    band_h = max(220, enlarged.shape[0] // 5)
    for frac in (0.18, 0.30, 0.42):
        y1 = int(enlarged.shape[0] * frac)
        y2 = min(enlarged.shape[0], y1 + band_h)
        if y2 - y1 > 70:
            band = enlarged[y1:y2, :]
            _, _, band_bw = _prep_variants(band)
            numeric = _ocr(band_bw, "--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789/-.")
            if numeric:
                results.append("DATE_SCAN " + numeric)

    for crop, label in focused[:5]:
        if crop.size == 0 or crop.shape[1] < 250:
            continue
        c_gray, c_clahe, c_bw = _prep_variants(crop)
        # Normal OCR preserves context.
        normal = _ocr(c_clahe, "--oem 3 --psm 6")
        if normal:
            results.append(normal)
        # Numeric OCR preserves tiny date stamps that normal OCR often loses.
        numeric = _ocr(c_bw, "--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789/-.")
        if numeric:
            results.append("DATE_SCAN " + numeric)

    return results


def extract_text(image_path):
    image = cv2.imread(image_path)
    if image is None:
        return ""

    h, w = image.shape[:2]
    # Normal whole-image OCR is intentionally limited for speed.
    target_w = min(max(w, 1400), 1900)
    scale = target_w / float(w)
    image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray, clahe, bw = _prep_variants(image)

    results = []
    # Two whole-image passes for product name + labels.
    for variant, config in ((clahe, "--oem 3 --psm 11"), (bw, "--oem 3 --psm 11")):
        text = _ocr(variant, config)
        if text:
            results.append(text)

    # One focused high-resolution label zone. It is still a single OCR pass,
    # but gives tiny printed dates substantially more pixels than full-image OCR.
    zh1, zh2 = int(image.shape[0] * 0.55), int(image.shape[0] * 0.75)
    date_zone = image[zh1:zh2, :]
    zone = cv2.resize(date_zone, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    zone_gray = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY)
    zone_adapt = cv2.adaptiveThreshold(zone_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY, 41, 11)
    zone_text = _ocr(zone_adapt, "--oem 3 --psm 11")
    if zone_text:
        results.append(zone_text)

    # High-resolution targeted pass for tiny MFG/EXP/Best Before text.
    results.extend(_targeted_date_crops(image))

    unique = []
    for item in results:
        cleaned = item.strip()
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return "\n".join(unique)
