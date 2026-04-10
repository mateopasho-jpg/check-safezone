from __future__ import annotations
import base64, io, logging, os, re
from typing import Any, Dict, List, Optional
import easyocr, requests
from fastapi import FastAPI, HTTPException, Header
from PIL import Image, ImageDraw
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="Safe Zone Check Service", version="1.0.0")

SAFE_TOP_PCT    = 0.14
SAFE_BOTTOM_PCT = 0.20
SAFE_LEFT_PCT   = 0.06
SAFE_RIGHT_PCT  = 0.06

_reader = None
def get_reader():
    global _reader
    if _reader is None:
        logger.info("Initialising EasyOCR reader...")
        _reader = easyocr.Reader(["de", "en"], gpu=False, verbose=False)
        logger.info("EasyOCR ready.")
    return _reader

class CheckRequest(BaseModel):
    file_id: str
    file_name: Optional[str] = None
    visualize: Optional[bool] = True

def _require_api_key(x_api_key):
    expected = (os.getenv("SERVICE_API_KEY") or "").strip()
    if not expected:
        return
    if not x_api_key or x_api_key.strip() != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

def _download_image(file_id: str) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "image/*,*/*;q=0.8",
    }
    sess = requests.Session()
    urls = [
        "https://drive.google.com/uc?export=download&id=" + file_id + "&confirm=t",
        "https://drive.google.com/uc?export=download&id=" + file_id,
        "https://lh3.googleusercontent.com/d/" + file_id,
    ]
    last_error = None
    for url in urls:
        try:
            resp = sess.get(url, headers=headers, timeout=60, allow_redirects=True)
            resp.raise_for_status()
            raw = resp.content or b""
            ct = (resp.headers.get("Content-Type") or "").lower()
            head = raw[:512].lstrip().lower()
            is_html = ("text/html" in ct) or head.startswith(b"<!doctype") or head.startswith(b"<html")
            if is_html:
                logger.warning("Got HTML from %s", url)
                text = raw[:100000].decode("utf-8", errors="ignore")
                m = re.search("confirm=([^& ]+)", text)
                if m:
                    confirm = m.group(1)
                    retry_url = "https://drive.google.com/uc?export=download&id=" + file_id + "&confirm=" + confirm
                    r2 = sess.get(retry_url, headers=headers, timeout=60, allow_redirects=True)
                    r2.raise_for_status()
                    raw2 = r2.content or b""
                    h2 = raw2[:512].lstrip().lower()
                    if not h2.startswith(b"<!doctype") and not h2.startswith(b"<html") and len(raw2) > 1024:
                        return raw2
                continue
            if len(raw) < 1024:
                continue
            return raw
        except Exception as e:
            last_error = e
            logger.warning("Failed %s: %s", url, e)
    raise ValueError("Could not download image. Last error: " + str(last_error))

def _run_check_and_visualize(image_bytes: bytes, visualize: bool):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = img.size

    safe_top    = height * SAFE_TOP_PCT
    safe_bottom = height * (1 - SAFE_BOTTOM_PCT)
    safe_left   = width  * SAFE_LEFT_PCT
    safe_right  = width  * (1 - SAFE_RIGHT_PCT)

    logger.info("Image: %dx%dpx", width, height)
    results = get_reader().readtext(image_bytes, detail=1)

    violations = []
    all_detections = []
    for (bbox, text, confidence) in results:
        if confidence < 0.3:
            continue
        xs = [pt[0] for pt in bbox]
        ys = [pt[1] for pt in bbox]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        zones = []
        if y_min < safe_top:    zones.append("top 14%")
        if y_max > safe_bottom: zones.append("bottom 20%")
        if x_min < safe_left:   zones.append("left 6%")
        if x_max > safe_right:  zones.append("right 6%")
        is_violation = len(zones) > 0
        all_detections.append((x_min, y_min, x_max, y_max, text, confidence, zones, is_violation))
        if is_violation:
            violations.append({
                "text": text,
                "confidence": round(confidence, 2),
                "zone": ", ".join(zones),
                "position": {"x_min": round(x_min), "y_min": round(y_min),
                             "x_max": round(x_max), "y_max": round(y_max)},
            })
            logger.warning("Violation: '%s' in %s", text, zones)

    preview_b64 = None
    if visualize:
        # Scale down for preview (max 600px wide)
        scale = min(1.0, 600 / width)
        preview_w = int(width * scale)
        preview_h = int(height * scale)
        preview = img.resize((preview_w, preview_h), Image.LANCZOS)
        draw = ImageDraw.Draw(preview, "RGBA")

        # Draw danger zones (semi-transparent red overlay)
        danger_color = (220, 50, 50, 80)
        # top zone
        draw.rectangle([0, 0, preview_w, int(safe_top * scale)], fill=danger_color)
        # bottom zone
        draw.rectangle([0, int(safe_bottom * scale), preview_w, preview_h], fill=danger_color)
        # left zone
        draw.rectangle([0, 0, int(safe_left * scale), preview_h], fill=danger_color)
        # right zone
        draw.rectangle([int(safe_right * scale), 0, preview_w, preview_h], fill=danger_color)

        # Draw safe zone border (green dashed line simulation)
        border_color = (0, 200, 0, 255)
        border_w = max(2, int(3 * scale))
        draw.rectangle(
            [int(safe_left * scale), int(safe_top * scale),
             int(safe_right * scale), int(safe_bottom * scale)],
            outline=border_color, width=border_w
        )

        # Draw detected text boxes
        for (x_min, y_min, x_max, y_max, text, conf, zones, is_violation) in all_detections:
            color = (255, 50, 50, 255) if is_violation else (50, 200, 50, 255)
            draw.rectangle(
                [int(x_min * scale), int(y_min * scale),
                 int(x_max * scale), int(y_max * scale)],
                outline=color, width=max(2, int(2 * scale))
            )
            # Label
            label = text[:20] + ("..." if len(text) > 20 else "")
            draw.text((int(x_min * scale), int(y_min * scale) - 14),
                      label, fill=color)

        buf = io.BytesIO()
        preview.save(buf, format="JPEG", quality=85)
        preview_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    return violations, preview_b64

@app.get("/health")
def health():
    return {"ok": True, "service": "safezone-check"}

@app.post("/check-safezone")
def check_safezone(req: CheckRequest,
                   x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    _require_api_key(x_api_key)
    file_name = req.file_name or req.file_id
    try:
        image_bytes = _download_image(req.file_id)
    except Exception as e:
        raise HTTPException(status_code=422, detail="Could not download image: " + str(e))
    try:
        violations, preview_b64 = _run_check_and_visualize(image_bytes, True)
    except Exception as e:
        raise HTTPException(status_code=500, detail="OCR processing failed: " + str(e))

    passed = len(violations) == 0
    result = {
        "ok": True,
        "file_id": req.file_id,
        "file_name": file_name,
        "passed": passed,
        "violations": violations,
    }
    if preview_b64:
        result["preview_base64"] = preview_b64

    if not passed:
        parts = ["'" + v["text"] + "' (" + v["zone"] + ")" for v in violations]
        result["message"] = "Safe zone violation in *" + file_name + "*: Text outside safe zone - " + ", ".join(parts)
    else:
        result["message"] = file_name + " passed safe zone check."
    return result