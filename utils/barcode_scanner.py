from pyzbar.pyzbar import decode
from PIL import Image
def scan_barcode(image_path):
    try:
        image=Image.open(image_path); results=decode(image)
        if results:return results[0].data.decode("utf-8",errors="ignore")
    except Exception as e: print("Barcode scan error:",e)
    return None
