ExpiryWatch - Hackathon Build

Core flow:
1. Front product photo is required and stored as the product identity image.
2. Additional photos are optional. The whole uploaded image(s) are scanned automatically.
3. OCR uses fast whole-image passes plus a high-resolution lower-package date zone and targeted tiny-text passes.
4. Date detector supports MFG/MFD/EXP/Expiry/Best Before/Use By and numeric MM-YY, MM-YYYY and full dates.
5. Printed expiry has priority. If a package explicitly states shelf life, MFG + shelf life is calculated.
6. Manufacturing date can be corrected by the user; expiry remains system-controlled.
7. SQLite stores products, original front photo, barcode, OCR text, dates, confidence and status.
8. Dashboard provides search, category filtering, countdown, notifications and expired history.

Important design rule:
ExpiryWatch does not invent an exact expiry from category alone. It uses package evidence first and only calculates from an explicit shelf-life rule.

Run on Windows (PowerShell):
C:\Users\ADMIN\projects\ExpiryWatch\venv\Scripts\python.exe app.py

Then open: http://127.0.0.1:5000
