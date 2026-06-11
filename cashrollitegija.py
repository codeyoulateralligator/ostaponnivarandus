#!/usr/bin/env python3

import argparse
import hashlib
import html
import json
import re
import textwrap
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, portrait
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from tqdm import tqdm


BASE = "http://hirve.myftp.org:7777/cashroll/"
TABLE_URL = urljoin(BASE, "db_get_table.php")
RATES_URL = urljoin(BASE, "db_get_currency_rates.php")

OUT_DIR = Path("cashroll_output")
IMG_DIR = OUT_DIR / "images"
DEBUG_DIR = OUT_DIR / "debug"
PDF_PATH = OUT_DIR / "cashroll_catalog.pdf"
JSON_PATH = OUT_DIR / "cashroll_data.json"

# Put your banknote placeholder image next to this script with this exact filename.
PLACEHOLDER_IMAGE = Path("missing_note.png")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json,text/javascript,*/*;q=0.9",
    "Referer": urljoin(BASE, "list.php"),
}

GRADE_FULL = {
    "UNC": "Uncirculated",
    "AU": "About uncirculated",
    "EF/XF": "Extremely fine",
    "XF": "Extremely fine",
    "EF": "Extremely fine",
    "VF": "Very fine",
    "F": "Fine",
    "VG": "Very good",
    "G": "Good",
    "FR": "Fair",
    "PR": "Poor",
}


@dataclass
class Note:
    item_id: str
    country_code: str
    country: str
    currency_code: str
    currency: str
    face_value: str
    year: str
    catalog_code: str
    series: str
    grade: str
    grade_full: str
    front_url: str
    back_url: str
    front_image: Optional[str]
    back_image: Optional[str]
    status: str
    comment: str
    current_value_eur: str
    current_value_debug: str


def ensure_dirs() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    IMG_DIR.mkdir(exist_ok=True)
    DEBUG_DIR.mkdir(exist_ok=True)


def clean(s: Any) -> str:
    if s is None:
        return ""

    s = html.unescape(str(s))
    s = re.sub(r"<[^>]+>", " ", s)

    return " ".join(s.replace("\xa0", " ").split())


def safe_filename_piece(s: str) -> str:
    s = clean(s)
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s)
    return s[:80] if s else "unknown"


def abs_url(url: str) -> str:
    url = clean(url)

    if not url:
        return ""

    return urljoin(BASE, url)


def image_original_url(url: str) -> str:
    url = abs_url(url)

    if not url:
        return ""

    if url.endswith("=s0"):
        return url

    if "googleusercontent" in url or "ggpht" in url:
        return url + "=s0"

    return url


def safe_img_name(url: str) -> str:
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()

    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        ext = ".jpg"

    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]

    return f"{h}{ext}"


def verify_image(path: Path) -> bool:
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:
        return False


def get_placeholder_path() -> Optional[str]:
    if PLACEHOLDER_IMAGE.exists():
        return str(PLACEHOLDER_IMAGE.resolve())

    return None


def download_image(session: requests.Session, url: str) -> Optional[str]:
    if not url:
        return None

    candidates = []
    original = image_original_url(url)
    normal = abs_url(url)

    if original:
        candidates.append(original)

    if normal and normal not in candidates:
        candidates.append(normal)

    for candidate in candidates:
        try:
            path = IMG_DIR / safe_img_name(candidate)

            if path.exists() and path.stat().st_size > 0 and verify_image(path):
                return str(path)

            r = session.get(candidate, headers=HEADERS, timeout=40)
            r.raise_for_status()

            path.write_bytes(r.content)

            if verify_image(path):
                return str(path)

            path.unlink(missing_ok=True)

        except Exception:
            continue

    print(f"WARNING: failed image: {url}")

    return None


def fetch_table(session: requests.Session) -> list[list[Any]]:
    r = session.get(TABLE_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()

    DEBUG_DIR.joinpath("db_get_table_raw.txt").write_text(
        r.text,
        encoding="utf-8",
        errors="ignore",
    )

    payload = r.json()

    DEBUG_DIR.joinpath("db_get_table.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if isinstance(payload, dict):
        for key in ["data", "aaData", "rows", "result", "results"]:
            if isinstance(payload.get(key), list):
                return payload[key]

    if isinstance(payload, list):
        return payload

    raise RuntimeError("Could not find rows in db_get_table.php JSON output")


def get_current_value_debug(
    session: requests.Session,
    currency_code: str,
    face_value: str,
    item_id: str = "",
) -> tuple[str, str]:
    currency_code = clean(currency_code)
    face_value = clean(face_value)
    item_id = clean(item_id)

    if not currency_code or not face_value:
        return "N/A", "missing currency_code or face_value"

    debug_file = DEBUG_DIR / (
        "currency_value_"
        + safe_filename_piece(item_id)
        + "_"
        + safe_filename_piece(currency_code)
        + "_"
        + safe_filename_piece(face_value)
        + ".json"
    )

    try:
        r = session.get(
            RATES_URL,
            headers=HEADERS,
            params={
                "currency": currency_code,
                "value": face_value,
            },
            timeout=20,
        )

        r.raise_for_status()

        raw = r.text.strip()

        try:
            payload = r.json()
        except Exception:
            debug_file.write_text(raw, encoding="utf-8", errors="ignore")
            return "N/A", f"non-JSON response | raw={raw[:180]}"

        debug_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        success = payload.get("success")
        conversion = payload.get("conversion") or {}

        src_currency = conversion.get("src_currency")
        dest_currency = conversion.get("dest_currency")
        src_value = conversion.get("src_value")
        dest_value = conversion.get("dest_value")
        rate = conversion.get("rate")

        if success is True and dest_value is not None and src_currency != dest_currency:
            pdf_value = f"{dest_value} €"
            debug = (
                f"OK converted | src={src_value} {src_currency} | "
                f"dest={dest_value} {dest_currency} | rate={rate}"
            )
            return pdf_value, debug

        debug = (
            f"N/A from endpoint | success={success} | "
            f"src={src_value} {src_currency} | "
            f"dest={dest_value} {dest_currency} | "
            f"rate={rate} | raw={raw[:180]}"
        )

        return "N/A", debug

    except Exception as e:
        return "N/A", f"request/error: {e}"


def row_to_note(
    row: list[Any],
    session: requests.Session,
    download_images: bool = True,
    debug_values: bool = True,
) -> Note:
    def val(i: int) -> str:
        return clean(row[i]) if i < len(row) else ""

    grade = val(9)
    front_url = val(10)
    back_url = val(11)

    current_value_eur, current_value_debug = get_current_value_debug(
        session=session,
        currency_code=val(3),
        face_value=val(5),
        item_id=val(0),
    )

    if debug_values:
        print(
            "[VALUE DEBUG] "
            f"ID={val(0)} | "
            f"title={val(5)} {val(4)} ({val(3)}) | "
            f"country={val(2)} | "
            f"year={val(6)} | "
            f"pdf_value={current_value_eur} | "
            f"{current_value_debug}"
        )

    placeholder = get_placeholder_path()

    front_img = download_image(session, front_url) if download_images else None
    back_img = download_image(session, back_url) if download_images else None

    if not front_img:
        front_img = placeholder

    if not back_img:
        back_img = placeholder

    return Note(
        item_id=val(0),
        country_code=val(1),
        country=val(2),
        currency_code=val(3),
        currency=val(4),
        face_value=val(5),
        year=val(6),
        catalog_code=val(7),
        series=val(8),
        grade=grade,
        grade_full=GRADE_FULL.get(grade, grade),
        front_url=abs_url(front_url),
        back_url=abs_url(back_url),
        front_image=front_img,
        back_image=back_img,
        status=val(12),
        comment=val(13),
        current_value_eur=current_value_eur,
        current_value_debug=current_value_debug,
    )


def image_size(path: Optional[str]) -> tuple[int, int]:
    if not path:
        return 0, 0

    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return 0, 0


def draw_image_fit(
    c: canvas.Canvas,
    path: Optional[str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    """
    Draw image inside a tight box. The box is sized close to a banknote aspect ratio,
    so there is less left/right whitespace.
    """
    c.setStrokeColor(colors.HexColor("#bcc6d3"))
    c.setLineWidth(0.5)
    c.setFillColor(colors.white)
    c.rect(x, y, w, h, stroke=1, fill=1)

    if not path or not Path(path).exists():
        c.setFillColor(colors.HexColor("#777777"))
        c.setFont("Helvetica", 7)
        c.drawCentredString(x + w / 2, y + h / 2, "No image")
        return

    iw, ih = image_size(path)

    if iw <= 0 or ih <= 0:
        c.setFillColor(colors.HexColor("#777777"))
        c.setFont("Helvetica", 7)
        c.drawCentredString(x + w / 2, y + h / 2, "Bad image")
        return

    inner_pad = 0.8 * mm
    avail_w = max(1, w - 2 * inner_pad)
    avail_h = max(1, h - 2 * inner_pad)

    scale = min(avail_w / iw, avail_h / ih)
    dw = iw * scale
    dh = ih * scale

    dx = x + inner_pad + (avail_w - dw) / 2
    dy = y + inner_pad + (avail_h - dh) / 2

    c.drawImage(
        path,
        dx,
        dy,
        dw,
        dh,
        preserveAspectRatio=True,
        mask="auto",
    )


def wrapped_lines(text: str, width: int) -> list[str]:
    lines = []

    for raw in text.splitlines():
        lines.extend(textwrap.wrap(raw, width=width) or [""])

    return lines


def draw_fitted_wrapped(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    max_width_pt: float,
    max_height_pt: float,
    start_size: float = 5.7,
    min_size: float = 4.2,
    step: float = 0.2,
    line_spacing: float = 1.10,
) -> None:
    size = start_size

    while size >= min_size:
        avg_char_width = max(1.0, size * 0.50)
        width_chars = max(18, int(max_width_pt / avg_char_width))
        lines = wrapped_lines(text, width_chars)
        line_h = size * line_spacing
        total_h = len(lines) * line_h

        if total_h <= max_height_pt:
            c.setFont("Helvetica", size)
            yy = y

            for line in lines:
                c.drawString(x, yy, line)
                yy -= line_h

            return

        size -= step

    size = min_size
    avg_char_width = max(1.0, size * 0.50)
    width_chars = max(18, int(max_width_pt / avg_char_width))
    lines = wrapped_lines(text, width_chars)
    line_h = size * line_spacing
    max_lines = max(1, int(max_height_pt / line_h))
    lines = lines[:max_lines]

    if lines:
        last = lines[-1]
        if len(last) > 3:
            lines[-1] = last[:-3] + "..."

    c.setFont("Helvetica", size)
    yy = y

    for line in lines:
        c.drawString(x, yy, line)
        yy -= line_h


def note_title(note: Note) -> str:
    currency = note.currency

    if note.currency_code:
        currency += f" ({note.currency_code})"

    title = f"{note.face_value} {currency}".strip()

    if note.country:
        title += f" — {note.country}"

    if note.year:
        title += f", {note.year}"

    return title


def note_details(note: Note) -> str:
    lines = [
        f"Country: {note.country}",
        f"Year: {note.year}",
        f"Currency code: {note.currency_code}",
        f"Value: {note.current_value_eur}",
        f"Catalog code: {note.catalog_code}",
        f"Series: {note.series}",
        f"Grade: {note.grade_full}",
        f"Status: {note.status}",
    ]

    if note.comment:
        lines.append(f"Comment: {note.comment.strip()}")

    return "\n".join(line for line in lines if not line.endswith(": "))


def draw_description_box(
    c: canvas.Canvas,
    note: Note,
    idx: int,
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    c.setStrokeColor(colors.HexColor("#bcc6d3"))
    c.setLineWidth(0.5)
    c.setFillColor(colors.white)
    c.rect(x, y, w, h, stroke=1, fill=1)

    inner_pad = 1.4 * mm
    tx = x + inner_pad
    ty = y + h - inner_pad - 5.4

    title = note_title(note)

    c.setFillColor(colors.HexColor("#0f172a"))
    c.setFont("Helvetica-Bold", 6.4)
    c.drawString(tx, ty, title[:90])

    details_top = ty - 6.0
    available_h = details_top - y - inner_pad - 4.0

    c.setFillColor(colors.HexColor("#111827"))
    draw_fitted_wrapped(
        c,
        note_details(note),
        tx,
        details_top,
        max_width_pt=w - 2 * inner_pad,
        max_height_pt=available_h,
        start_size=5.5,
        min_size=4.1,
        step=0.2,
        line_spacing=1.08,
    )

    c.setFillColor(colors.HexColor("#64748b"))
    c.setFont("Helvetica", 5.0)
    c.drawRightString(x + w - inner_pad, y + inner_pad, f"#{idx + 1} | ID {note.item_id}")


def draw_note_card(
    c: canvas.Canvas,
    note: Note,
    idx: int,
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.setStrokeColor(colors.HexColor("#cbd5e1"))
    c.setLineWidth(0.7)
    c.roundRect(x, y, w, h, 4, stroke=1, fill=1)

    # Very tight card padding so image boxes rise almost to the card border.
    pad = 1.4 * mm
    gap = 1.7 * mm

    ix = x + pad
    iy = y + pad
    iw = w - 2 * pad
    ih = h - 2 * pad

    # Images now use full card height because title moved to the right box.
    img_h = ih

    # Banknotes are usually about 2.05–2.35 wide for their height.
    # This keeps the white image box tighter and removes wasted left/right space.
    preferred_note_box_ratio = 2.28
    img_w = img_h * preferred_note_box_ratio

    # Do not let the two image boxes eat too much space.
    max_image_total_w = iw * 0.66
    if (img_w * 2 + gap) > max_image_total_w:
        img_w = (max_image_total_w - gap) / 2

    image_total_w = img_w * 2 + gap

    desc_x = ix + image_total_w + gap
    desc_w = iw - image_total_w - gap

    draw_image_fit(c, note.front_image, ix, iy, img_w, img_h)
    draw_image_fit(c, note.back_image, ix + img_w + gap, iy, img_w, img_h)

    draw_description_box(
        c=c,
        note=note,
        idx=idx,
        x=desc_x,
        y=iy,
        w=desc_w,
        h=img_h,
    )


def make_pdf(notes: list[Note], pdf_path: Path, per_page: int = 8) -> None:
    """
    Portrait A4, 1 column, 8 rows.
    """
    page_size = portrait(A4)
    c = canvas.Canvas(str(pdf_path), pagesize=page_size)

    page_w, page_h = page_size
    margin = 8 * mm
    gap = 3 * mm

    rows = per_page

    cell_w = page_w - 2 * margin
    cell_h = (page_h - 2 * margin - (rows - 1) * gap) / rows

    total_pages = (len(notes) + per_page - 1) // per_page if notes else 1

    for idx, note in enumerate(notes):
        pos = idx % per_page

        if idx > 0 and pos == 0:
            page_num = idx // per_page
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.HexColor("#5b6470"))
            c.drawCentredString(page_w / 2, 5 * mm, f"Page {page_num} / {total_pages}")
            c.showPage()

        row = pos
        x = margin
        y = page_h - margin - (row + 1) * cell_h - row * gap

        draw_note_card(c, note, idx, x, y, cell_w, cell_h)

    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#5b6470"))
    c.drawCentredString(page_w / 2, 5 * mm, f"Page {total_pages} / {total_pages}")

    c.save()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(PDF_PATH))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--per-page", type=int, default=8)
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument("--delay", type=float, default=0.03)
    parser.add_argument(
        "--no-value-debug",
        action="store_true",
        help="Disable console debug lines for currency/value retrieval.",
    )
    args = parser.parse_args()

    ensure_dirs()

    if not PLACEHOLDER_IMAGE.exists():
        print()
        print(f"WARNING: Placeholder image not found: {PLACEHOLDER_IMAGE}")
        print("Save the banknote placeholder image as 'missing_note.png' next to this script.")
        print()

    session = requests.Session()
    session.headers.update(HEADERS)

    print(f"Fetching table JSON: {TABLE_URL}")
    rows = fetch_table(session)
    print(f"Rows found: {len(rows)}")

    if args.limit > 0:
        rows = rows[:args.limit]

    notes: list[Note] = []

    for row in tqdm(rows, desc="Processing rows"):
        try:
            note = row_to_note(
                row=row,
                session=session,
                download_images=not args.no_images,
                debug_values=not args.no_value_debug,
            )
            notes.append(note)
        except Exception as e:
            print(f"WARNING: failed row: {e}")

        time.sleep(args.delay)

    notes.sort(
        key=lambda n: (
            n.country.lower(),
            n.currency.lower(),
            n.currency_code.lower(),
            n.series.lower(),
            n.face_value.lower(),
            n.year.lower(),
        )
    )

    JSON_PATH.write_text(
        json.dumps([asdict(n) for n in notes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Creating PDF: {args.out}")
    make_pdf(notes, Path(args.out), per_page=args.per_page)

    print()
    print("Done.")
    print(f"Notes: {len(notes)}")
    print(f"JSON: {JSON_PATH}")
    print(f"Images: {IMG_DIR}")
    print(f"Debug: {DEBUG_DIR}")
    print(f"PDF: {args.out}")


if __name__ == "__main__":
    main()