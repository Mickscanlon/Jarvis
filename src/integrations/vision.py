"""
vision.py - PDF reading, image OCR, and Claude vision for rich interpretation
"""
import os
import logging
import base64
from typing import Optional

logger = logging.getLogger(__name__)


def read_pdf(filepath: str, max_pages: int = 20) -> str:
    """Extract text from a PDF using PyMuPDF."""
    try:
        import fitz
        doc = fitz.open(filepath)
        pages = min(len(doc), max_pages)
        text_parts = []
        for i in range(pages):
            page = doc[i]
            text_parts.append(f"--- Page {i+1} ---\n{page.get_text()}")
        doc.close()
        full_text = "\n\n".join(text_parts)

        if len(full_text) > 10000:
            from llm import chat
            result = chat([
                {"role": "user", "content":
                 f"Summarise this PDF document. Key facts, main topics, important numbers.\n\n{full_text[:8000]}"}
            ], tier=2)
            return f"[PDF Summary]\n{result['content']}\n\n[Full text truncated at {len(full_text)} chars]"
        return full_text or "No text found in PDF."
    except ImportError:
        return "PyMuPDF not installed. Run: pip install pymupdf"
    except Exception as e:
        return f"PDF read error: {e}"


def read_image(filepath: str) -> str:
    """OCR an image file. Falls back to Claude vision if confidence is low."""
    try:
        import pytesseract
        from PIL import Image
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

        img = Image.open(filepath)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data["conf"] if c != "-1"]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0
        text = pytesseract.image_to_string(img).strip()

        if avg_conf < 60 and os.getenv("ANTHROPIC_API_KEY"):
            return _claude_vision(filepath, "Extract and transcribe all text visible in this image.")
        return text or "No text detected."
    except Exception as e:
        return f"Image read error: {e}"


def capture_webcam() -> Optional[str]:
    """Capture a frame from the default webcam. Returns temp file path."""
    try:
        import cv2
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return None
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return None
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        cv2.imwrite(tmp.name, frame)
        return tmp.name
    except Exception:
        return None


def _claude_vision(filepath: str, prompt: str) -> str:
    """Send an image to Claude Sonnet for interpretation."""
    try:
        import anthropic
        with open(filepath, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")

        ext = os.path.splitext(filepath)[1].lower()
        media_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
        media_type = media_map.get(ext, "image/jpeg")

        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": img_data,
                    }},
                    {"type": "text", "text": prompt}
                ]
            }]
        )
        return response.content[0].text
    except Exception as e:
        return f"Vision error: {e}"


def describe_image(filepath: str) -> str:
    """Get a rich description of an image via Claude vision or OCR."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return _claude_vision(filepath, "Describe what you see in this image. Include any text, objects, people, or relevant context.")
    return read_image(filepath)


def look_at_webcam() -> str:
    """Capture webcam frame and describe it."""
    path = capture_webcam()
    if not path:
        return "No webcam detected, sir."
    result = describe_image(path)
    try:
        os.unlink(path)
    except Exception:
        pass
    return result
