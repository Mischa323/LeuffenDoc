"""Photos and files on an item: what is shown, who may, and where they go."""
import io
import zipfile

from PIL import Image

from app import database


def photo(size=(1200, 800), fmt="JPEG"):
    buf = io.BytesIO()
    Image.new("RGB", size, (40, 120, 200)).save(buf, fmt)
    return buf.getvalue()


def test_a_photo_is_shown_and_a_file_is_downloaded(admin, org, make):
    item = make(admin, "network", "SW-FOTO", {"role": "Switch"})
    shot = admin.post(f"/api/items/{item['id']}/attachments?name=rack.jpg", content=photo(),
                      headers={"Content-Type": "image/jpeg"})
    assert shot.status_code == 200, shot.text
    pic = shot.json()
    assert pic["is_image"] and pic["mime"] == "image/jpeg" and (pic["width"], pic["height"]) == (1200, 800)
    shown = admin.get(f"/api/attachments/{pic['id']}/file")
    assert shown.headers["content-type"] == "image/jpeg"
    assert shown.headers["content-disposition"].startswith("inline")
    thumb = admin.get(f"/api/attachments/{pic['id']}/thumb")
    assert thumb.status_code == 200 and max(Image.open(io.BytesIO(thumb.content)).size) <= 480

    # Named like a picture, but it is not one: a file to download, never shown.
    fake = admin.post(f"/api/items/{item['id']}/attachments?name=geen-foto.png",
                      content=b"<script>alert(1)</script>", headers={"Content-Type": "image/png"}).json()
    assert not fake["is_image"]
    got = admin.get(f"/api/attachments/{fake['id']}/file")
    assert got.headers["content-type"] == "application/octet-stream"
    assert got.headers["content-disposition"].startswith("attachment")
    # An SVG can carry a script: a download too.
    svg = admin.post(f"/api/items/{item['id']}/attachments?name=logo.svg",
                     content=b"<svg xmlns='http://www.w3.org/2000/svg'><script>x()</script></svg>").json()
    assert not svg["is_image"]
    assert admin.get(f"/api/attachments/{svg['id']}/file").headers["content-disposition"].startswith("attachment")

    pdf = admin.post(f"/api/items/{item['id']}/attachments?name=../../handleiding.pdf",
                     content=b"%PDF-1.7\n...").json()
    assert pdf["name"] == "handleiding.pdf" and pdf["mime"] == "application/pdf"

    names = [f["name"] for f in admin.get(f"/api/items/{item['id']}/attachments").json()]
    assert names == ["rack.jpg", "geen-foto.png", "logo.svg", "handleiding.pdf"]
    history = admin.get(f"/api/items/{item['id']}/revisions").json()
    assert any(c["to"] == "rack.jpg" for r in history for c in r["changes"])


def test_who_may(admin, member, viewer, outsider, org, make):
    item = make(admin, "computer", "WS-FOTO", {"role": "Desktop"})
    url = f"/api/items/{item['id']}/attachments?name=label.png"
    assert viewer.post(url, content=photo(fmt="PNG")).status_code == 403
    added = member.post(url, content=photo(fmt="PNG"))
    assert added.status_code == 200
    att = added.json()
    assert viewer.get(f"/api/attachments/{att['id']}/file").status_code == 200
    assert outsider.get(f"/api/attachments/{att['id']}/file").status_code == 404
    assert outsider.get(f"/api/items/{item['id']}/attachments").status_code == 404
    assert viewer.delete(f"/api/attachments/{att['id']}").status_code == 403
    assert member.delete(f"/api/attachments/{att['id']}").status_code == 200
    assert admin.get(f"/api/items/{item['id']}/attachments").json() == []


def test_size_limit_and_going_with_the_item(admin, org, make):
    item = make(admin, "printer", "PR-FOTO", {"role": "Printer"})
    assert admin.put("/api/admin/settings", json={"DOC_ATTACH_MAX_MB": 1}).status_code == 200
    big = admin.post(f"/api/items/{item['id']}/attachments?name=groot.bin", content=b"x" * (1024 * 1024 + 1))
    assert big.status_code == 413 and "1 MB" in big.json()["detail"]
    assert admin.put("/api/admin/settings", json={"DOC_ATTACH_MAX_MB": 25}).status_code == 200
    att = admin.post(f"/api/items/{item['id']}/attachments?name=toner.jpg", content=photo()).json()

    # In the export: the file itself, and the page shows the photo.
    data = admin.post(f"/api/orgs/{org['id']}/export", json={"passwords": False}).content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        page = z.read(next(n for n in names if n.endswith("documentatie.html"))).decode()
        stored = [n for n in names if n.endswith("/toner.jpg")]
        assert stored and z.read(stored[0]) == database.attachment_data(att["id"])
    assert "toner.jpg" in page and "<img" in page

    # Deleting the item takes its files with it.
    assert admin.delete(f"/api/items/{item['id']}").status_code == 200
    assert database.get_attachment(att["id"]) is None
