from datetime import datetime
from dateutil.relativedelta import relativedelta
import re

CATEGORY_RULES = {
    "Groceries / Food": "Use the package's EXP/Best Before or stated shelf life.",
    "Dairy": "Use the package's Use By/Best Before or stated shelf life.",
    "Cosmetics": "Use printed expiry or MFG + stated shelf life/PAO; do not invent a date.",
    "Personal Care": "Use printed expiry or MFG + stated shelf life; do not invent a date.",
    "Medicines": "Use the printed expiry only; no category-based date is invented.",
    "Household": "Use printed expiry or stated shelf life where applicable.",
    "Others": "Use the product label evidence available.",
}


def extract_shelf_life(text):
    if not text:
        return None
    for pattern, multiplier in [
        (r"\b(\d{1,3})\s*(?:MONTHS?|MOS?)\b", 1),
        (r"\b(\d{1,2})\s*(?:YEARS?|YRS?)\b", 12),
    ]:
        match = re.search(pattern, text.upper())
        if match:
            months = int(match.group(1)) * multiplier
            if 1 <= months <= 120:
                return months
    return None


def parse_manufacturing_date(date_text):
    if not date_text:
        return None
    s = date_text.strip().replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1")
    m = re.search(r"\b(0?[1-9]|1[0-2])\s*[/\-.]\s*(20\d{2})\b", s)
    if m:
        return datetime(int(m.group(2)), int(m.group(1)), 1)
    m = re.search(r"\b(0?[1-9]|1[0-2])\s*[/\-.]\s*(\d{2})\b", s)
    if m:
        return datetime(2000 + int(m.group(2)), int(m.group(1)), 1)
    m = re.search(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(20\d{2})\b", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def estimate_expiry(text, manufacturing_date):
    months = extract_shelf_life(text)
    mfg = parse_manufacturing_date(manufacturing_date)
    if not months or not mfg:
        return None
    return (mfg + relativedelta(months=months)).strftime("%m/%Y")


def detect_category(text):
    t = (text or "").upper()
    rules = [
        ("Dairy", ["MILK", "CURD", "YOGURT", "BUTTER", "CHEESE", "PANEER"]),
        ("Cosmetics", ["SHAMPOO", "CREAM", "LOTION", "FACE WASH", "MAKEUP", "SERUM"]),
        ("Personal Care", ["DEODORANT", "BODY SPRAY", "PERFUME", "TOOTHPASTE", "SOAP"]),
        ("Medicines", ["TABLET", "CAPSULE", "SYRUP", "MG/", "PHARMA"]),
        ("Groceries / Food", ["BISCUIT", "SNACK", "FOOD", "JUICE", "SAUCE", "CHOCOLATE"]),
        ("Household", ["DETERGENT", "CLEANER", "DISINFECTANT", "WASHING POWDER"]),
    ]
    for category, words in rules:
        if any(word in t for word in words):
            name = "Deodorant" if category == "Personal Care" and "DEODORANT" in t else category
            return category, name
    return "Others", "Unknown Product"
