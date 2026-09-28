"""QR image generation. Payloads are short text strings, so QRs stay scannable."""

import base64
import io

import qrcode


def qr_data_uri(payload, box_size=6):
    """Return a data URI PNG of the QR code for the given payload string."""
    qr = qrcode.QRCode(box_size=box_size, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
