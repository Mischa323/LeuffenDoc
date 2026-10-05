"""What a file somebody attached actually is.

The browser's word for it is not taken: a file called foto.jpg can be anything,
and whatever is shown *in* the page must really be a picture. Pillow decides
whether it is one (and makes the small copy the gallery shows, turned the way
the camera held it); a PDF is recognised by how it starts; everything else is
a file to download, never something the browser is asked to display.

An SVG is a picture that can carry a script, so it is a download here too.
"""
from __future__ import annotations

import io
import mimetypes
import re

# Pictures the page shows itself, by the format Pillow finds -- not by name.
SHOWN = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
THUMB_EDGE = 480


def clean_name(name: str) -> str:
    """A file name as it may be shown and offered for download: no folders, no
    control characters, not endless."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    return name[:120] or "bestand"


def inspect(data: bytes, name: str) -> dict:
    """mime, whether it is a picture shown in the page, its size and a thumbnail."""
    out = {"mime": "application/octet-stream", "is_image": False, "width": None, "height": None,
           "thumb": None}
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()                      # a damaged file stops here
        if fmt in SHOWN:
            with Image.open(io.BytesIO(data)) as img:
                img = ImageOps.exif_transpose(img)
                out.update(mime=SHOWN[fmt], is_image=True, width=img.width, height=img.height)
                small = img.convert("RGBA") if img.mode in ("P", "LA") else img
                if small.mode == "RGBA":
                    backdrop = Image.new("RGB", small.size, (255, 255, 255))
                    backdrop.paste(small, mask=small.split()[-1])
                    small = backdrop
                elif small.mode != "RGB":
                    small = small.convert("RGB")
                small.thumbnail((THUMB_EDGE, THUMB_EDGE))
                buf = io.BytesIO()
                small.save(buf, "JPEG", quality=82, optimize=True)
                out["thumb"] = buf.getvalue()
            return out
    except Exception:
        pass                                    # not a picture Pillow can read: a file
    if data[:5] == b"%PDF-":
        out["mime"] = "application/pdf"
        return out
    guessed = mimetypes.guess_type(name)[0]
    if guessed and not guessed.startswith(("image/", "text/html", "application/xhtml")):
        out["mime"] = guessed
    return out
