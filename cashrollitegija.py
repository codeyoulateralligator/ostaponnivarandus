#!/usr/bin/env python3

import argparse
import getpass
import hashlib
import html
import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, portrait
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from rich import box
from rich.console import Console
from rich.table import Table
from tqdm import tqdm


BASE = "http://hirve.myftp.org:7777/cashroll/"
LIST_URL = urljoin(BASE, "list.php")
LOGIN_URL = urljoin(BASE, "login.php")
SESSION_URL = urljoin(BASE, "session.php")
TABLE_URL = urljoin(BASE, "db_get_table.php")
RATES_URL = urljoin(BASE, "db_get_currency_rates.php")

OUT_DIR = Path("cashroll_output")
IMG_DIR = OUT_DIR / "images"
DEBUG_DIR = OUT_DIR / "debug"
PDF_PATH = OUT_DIR / "cashroll_catalog.pdf"
JSON_PATH = OUT_DIR / "cashroll_data.json"

PLACEHOLDER_IMAGE = Path("missing_note.png")
DEFAULT_TITLE_MONEY_IMAGE = Path("ostaponn_money.png")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept": "application/json,text/javascript,*/*;q=0.9",
    "Referer": LIST_URL,
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
    item_price_eur: str
    shipping_eur: str
    total_cost_eur: str
    cost_debug: str


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


def parse_money_decimal(value: Any) -> Optional[Decimal]:
    s = clean(value)
    if not s:
        return None

    s = s.replace("€", "").replace(",", ".")
    s = re.sub(r"[^0-9.\-]", "", s)

    if not s:
        return None

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def money_str_to_decimal(value: str) -> Optional[Decimal]:
    return parse_money_decimal(value)


def fmt_money(value: Optional[Decimal]) -> str:
    if value is None:
        return ""
    return f"{value:.2f} €"


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


def find_title_money_image(path_arg: str = "") -> Optional[str]:
    candidates = []

    if path_arg:
        candidates.append(Path(path_arg))

    candidates.extend([
        DEFAULT_TITLE_MONEY_IMAGE,
        Path("ostaponn(1).png"),
        Path("ostaponn.png"),
    ])

    for p in candidates:
        if p.exists():
            return str(p.resolve())

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


def get_session_info(session: requests.Session) -> dict[str, Any]:
    try:
        r = session.get(SESSION_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()

        try:
            return r.json()
        except Exception:
            return {"raw": r.text[:300]}

    except Exception as e:
        return {"error": str(e)}


def login(session: requests.Session, username: str, password: str) -> bool:
    print(f"Logging in as: {username}")

    try:
        session.get(LIST_URL, headers=HEADERS, timeout=30).raise_for_status()
    except Exception as e:
        print(f"WARNING: initial list.php request failed before login: {e}")

    payload = {
        "username": username,
        "password": password,
        "remember_me": "0",
    }

    r = session.post(
        LOGIN_URL,
        headers={
            **HEADERS,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        },
        data=payload,
        timeout=30,
    )
    r.raise_for_status()

    raw = r.text.strip()
    DEBUG_DIR.joinpath("login_response.txt").write_text(raw, encoding="utf-8", errors="ignore")

    try:
        data = r.json()
    except Exception:
        data = {"raw": raw}

    print(f"Login response: {json.dumps(data, ensure_ascii=False)}")

    session_info = get_session_info(session)
    DEBUG_DIR.joinpath("session_after_login.json").write_text(
        json.dumps(session_info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    session_user = clean(session_info.get("session_user", ""))

    if session_user:
        print(f"Login OK. Session user: {session_user}")
        return True

    session_error = clean(data.get("session_error", "")) if isinstance(data, dict) else ""
    if session_error:
        print(f"Login failed: {session_error}")
    else:
        print("Login may have failed: session_user is empty.")

    return False


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


def extract_cost_fields(row: list[Any]) -> tuple[str, str, str, str]:
    raw_item_price = row[16] if len(row) > 16 else None
    raw_shipping = row[17] if len(row) > 17 else None

    item_price = parse_money_decimal(raw_item_price)
    shipping = parse_money_decimal(raw_shipping)

    item_price_str = fmt_money(item_price)
    shipping_str = fmt_money(shipping)

    total = None
    if item_price is not None or shipping is not None:
        total = (item_price or Decimal("0")) + (shipping or Decimal("0"))

    total_str = fmt_money(total)

    debug = (
        f"row_len={len(row)} | "
        f"raw_price={raw_item_price!r} -> {item_price_str or 'N/A'} | "
        f"raw_shipping={raw_shipping!r} -> {shipping_str or 'N/A'} | "
        f"total={total_str or 'N/A'}"
    )

    return item_price_str, shipping_str, total_str, debug


def row_to_note(
    row: list[Any],
    session: requests.Session,
    download_images: bool = True,
    debug_values: bool = True,
    debug_costs: bool = True,
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

    item_price_eur, shipping_eur, total_cost_eur, cost_debug = extract_cost_fields(row)

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

    if debug_costs:
        print(
            "[COST DEBUG] "
            f"ID={val(0)} | "
            f"{val(5)} {val(4)} ({val(3)}) | "
            f"{cost_debug}"
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
        item_price_eur=item_price_eur,
        shipping_eur=shipping_eur,
        total_cost_eur=total_cost_eur,
        cost_debug=cost_debug,
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


def draw_image_plain_fit(
    c: canvas.Canvas,
    path: Optional[str],
    x: float,
    y: float,
    w: float,
    h: float,
) -> None:
    if not path or not Path(path).exists():
        c.setFillColor(colors.HexColor("#75622f"))
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(x + w / 2, y + h / 2, "Missing title image")
        return

    iw, ih = image_size(path)
    if iw <= 0 or ih <= 0:
        return

    scale = min(w / iw, h / ih)
    dw = iw * scale
    dh = ih * scale

    c.drawImage(
        path,
        x + (w - dw) / 2,
        y + (h - dh) / 2,
        dw,
        dh,
        preserveAspectRatio=True,
        mask="auto",
    )


def wrap_text_to_width(text: str, font_name: str, font_size: float, max_width_pt: float) -> list[str]:
    output = []

    for raw_line in text.splitlines():
        words = raw_line.split()

        if not words:
            output.append("")
            continue

        line = ""

        for word in words:
            test = word if not line else f"{line} {word}"

            if stringWidth(test, font_name, font_size) <= max_width_pt:
                line = test
            else:
                if line:
                    output.append(line)
                line = word

        if line:
            output.append(line)

    return output


def build_label_value_rendered_lines(
    lines: list[tuple[str, str, bool]],
    size: float,
    max_width_pt: float,
) -> list[tuple]:
    rendered_lines = []

    for label, value, whole_bold in lines:
        if whole_bold:
            text = f"{label}{value}"
            wrapped = wrap_text_to_width(text, "Helvetica-Bold", size, max_width_pt)
            rendered_lines.extend([("BOLD_FULL", w) for w in wrapped])
        else:
            prefix_w = stringWidth(label, "Helvetica-Bold", size)
            available_for_first_value = max_width_pt - prefix_w
            value_words = value.split()

            if not value_words:
                rendered_lines.append(("LABEL_VALUE", label, ""))
                continue

            current = ""
            first_line_done = False

            for word in value_words:
                test = word if not current else f"{current} {word}"
                limit = available_for_first_value if not first_line_done else max_width_pt

                if stringWidth(test, "Helvetica", size) <= limit:
                    current = test
                else:
                    if not first_line_done:
                        rendered_lines.append(("LABEL_VALUE", label, current))
                        first_line_done = True
                    else:
                        rendered_lines.append(("NORMAL", current))
                    current = word

            if current:
                if not first_line_done:
                    rendered_lines.append(("LABEL_VALUE", label, current))
                else:
                    rendered_lines.append(("NORMAL", current))

    return rendered_lines


def draw_label_value_lines(
    c: canvas.Canvas,
    lines: list[tuple[str, str, bool]],
    x: float,
    y: float,
    max_width_pt: float,
    max_height_pt: float,
    start_size: float = 5.4,
    min_size: float = 4.1,
) -> None:
    size = start_size
    best_lines = []

    while size >= min_size:
        rendered_lines = build_label_value_rendered_lines(lines, size, max_width_pt)
        line_h = size * 1.12

        if len(rendered_lines) * line_h <= max_height_pt:
            best_lines = rendered_lines
            break

        size -= 0.2

    if size < min_size:
        size = min_size
        best_lines = build_label_value_rendered_lines(lines, size, max_width_pt)

    line_h = size * 1.12
    max_lines = max(1, int(max_height_pt / line_h))
    rendered_lines = best_lines[:max_lines]

    if len(best_lines) > max_lines and rendered_lines:
        last = rendered_lines[-1]
        if last[0] == "NORMAL":
            rendered_lines[-1] = ("NORMAL", last[1][:-3] + "..." if len(last[1]) > 3 else last[1])
        elif last[0] == "BOLD_FULL":
            rendered_lines[-1] = ("BOLD_FULL", last[1][:-3] + "..." if len(last[1]) > 3 else last[1])
        elif last[0] == "LABEL_VALUE":
            rendered_lines[-1] = ("LABEL_VALUE", last[1], last[2][:-3] + "..." if len(last[2]) > 3 else last[2])

    yy = y

    for item in rendered_lines:
        if item[0] == "BOLD_FULL":
            _, text = item
            c.setFont("Helvetica-Bold", size)
            c.drawString(x, yy, text)
        elif item[0] == "LABEL_VALUE":
            _, label, value = item
            c.setFont("Helvetica-Bold", size)
            c.drawString(x, yy, label)
            label_w = stringWidth(label, "Helvetica-Bold", size)
            c.setFont("Helvetica", size)
            c.drawString(x + label_w, yy, value)
        else:
            _, text = item
            c.setFont("Helvetica", size)
            c.drawString(x, yy, text)

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


def cost_display(note: Note) -> str:
    if not note.item_price_eur and not note.shipping_eur and not note.total_cost_eur:
        return ""

    if note.item_price_eur and note.shipping_eur:
        return f"{note.item_price_eur} + {note.shipping_eur} shipping = {note.total_cost_eur}"

    if note.item_price_eur:
        return note.item_price_eur

    if note.shipping_eur:
        return f"{note.shipping_eur} shipping"

    return note.total_cost_eur


def note_detail_lines(note: Note) -> list[tuple[str, str, bool]]:
    lines: list[tuple[str, str, bool]] = []

    cost = cost_display(note)
    if cost:
        lines.append(("Cost: ", cost, True))

    normal = [
        ("Country: ", note.country),
        ("Year: ", note.year),
        ("Currency code: ", note.currency_code),
        ("Value: ", note.current_value_eur),
        ("Catalog code: ", note.catalog_code),
        ("Series: ", note.series),
        ("Grade: ", note.grade_full),
        ("Status: ", note.status),
    ]

    for label, value in normal:
        if value:
            lines.append((label, value, False))

    if note.comment:
        lines.append(("Comment: ", note.comment.strip(), False))

    return lines


def compute_inventory_summary(notes: list[Note]) -> dict[str, Any]:
    priced_notes = []
    missing_price_notes = []

    raw_total = Decimal("0")
    shipping_total = Decimal("0")
    total_with_shipping = Decimal("0")

    for note in notes:
        raw_price = money_str_to_decimal(note.item_price_eur)
        shipping = money_str_to_decimal(note.shipping_eur)

        if raw_price is None:
            missing_price_notes.append(note)
            continue

        shipping = shipping or Decimal("0")
        total = raw_price + shipping

        raw_total += raw_price
        shipping_total += shipping
        total_with_shipping += total

        priced_notes.append((note, raw_price, shipping, total))

    priced_notes.sort(key=lambda x: x[1], reverse=True)

    avg_raw = Decimal("0")
    if priced_notes:
        avg_raw = raw_total / Decimal(len(priced_notes))

    return {
        "total_notes": len(notes),
        "priced_count": len(priced_notes),
        "missing_price_count": len(missing_price_notes),
        "raw_total": raw_total,
        "shipping_total": shipping_total,
        "total_with_shipping": total_with_shipping,
        "avg_raw": avg_raw,
        "priced_notes": priced_notes,
        "missing_price_notes": missing_price_notes,
        "created_at": datetime.now(),
    }


def print_inventory_stats(notes: list[Note], top_n: int = 100) -> None:
    console = Console()
    summary = compute_inventory_summary(notes)

    priced_notes = summary["priced_notes"]
    missing_price_notes = summary["missing_price_notes"]

    console.print()
    console.rule("[bold cyan]Inventory statistics")

    console.print(f"[bold]Total notes processed:[/bold] [cyan]{summary['total_notes']}[/cyan]")
    console.print(f"[bold]Notes with raw price:[/bold] [green]{summary['priced_count']}[/green]")
    console.print(f"[bold]Notes missing raw price:[/bold] [red]{summary['missing_price_count']}[/red]")
    console.print(f"[bold]Total inventory value, raw price only:[/bold] [bold yellow]{summary['raw_total']:.2f} €[/bold yellow]")
    console.print(f"[bold]Total shipping value:[/bold] [magenta]{summary['shipping_total']:.2f} €[/magenta]")
    console.print(f"[bold]Total including shipping:[/bold] [bold green]{summary['total_with_shipping']:.2f} €[/bold green]")

    if priced_notes:
        max_note, max_price, _, _ = priced_notes[0]
        min_note, min_price, _, _ = priced_notes[-1]

        console.print(f"[bold]Average raw price:[/bold] [cyan]{summary['avg_raw']:.2f} €[/cyan]")
        console.print(
            f"[bold]Most expensive:[/bold] [yellow]{max_price:.2f} €[/yellow] "
            f"[dim]ID {max_note.item_id}[/dim] {note_title(max_note)}"
        )
        console.print(
            f"[bold]Cheapest priced:[/bold] [yellow]{min_price:.2f} €[/yellow] "
            f"[dim]ID {min_note.item_id}[/dim] {note_title(min_note)}"
        )

    console.print()
    console.rule(f"[bold cyan]Top {min(top_n, len(priced_notes))} most expensive notes by raw price")

    table = Table(
        title=f"Top {min(top_n, len(priced_notes))} most expensive notes",
        box=box.ROUNDED,
        header_style="bold white on dark_blue",
        show_lines=False,
        row_styles=["none", "dim"],
    )

    table.add_column("#", justify="right", style="bold cyan", width=4)
    table.add_column("ID", justify="right", style="bright_black", width=6)
    table.add_column("Note", style="white", overflow="fold", max_width=48)
    table.add_column("Country", style="cyan", overflow="fold", max_width=18)
    table.add_column("Year", justify="right", style="bright_black", width=6)
    table.add_column("Grade", style="magenta", width=10)
    table.add_column("Raw price", justify="right", style="bold yellow", width=12)
    table.add_column("Shipping", justify="right", style="blue", width=10)
    table.add_column("Total", justify="right", style="bold green", width=12)

    for rank, (note, raw_price, shipping, total) in enumerate(priced_notes[:top_n], start=1):
        table.add_row(
            str(rank),
            note.item_id,
            note_title(note),
            note.country,
            note.year,
            note.grade or note.grade_full,
            f"{raw_price:.2f} €",
            f"{shipping:.2f} €" if shipping else "",
            f"{total:.2f} €",
        )

    console.print(table)

    if missing_price_notes:
        console.print()
        console.print(f"[yellow]Warning:[/yellow] {len(missing_price_notes)} notes had no raw price in row[16].")


def draw_multiline_text(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    max_width_pt: float,
    font_name: str,
    font_size: float,
    line_h: float,
    max_lines: int,
) -> float:
    """
    Draw wrapped text and return the next y position below it.
    """
    lines = wrap_text_to_width(text, font_name, font_size, max_width_pt)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if len(lines[-1]) > 3:
            lines[-1] = lines[-1][:-3] + "..."

    c.setFont(font_name, font_size)

    yy = y
    for line in lines:
        c.drawString(x, yy, line)
        yy -= line_h

    return yy

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
    top_y = y + h - inner_pad - 5.0
    max_text_w = w - 2 * inner_pad

    title = note_title(note)

    c.setFillColor(colors.HexColor("#0f172a"))

    # Multiline title instead of cutting it.
    after_title_y = draw_multiline_text(
        c=c,
        text=title,
        x=tx,
        y=top_y,
        max_width_pt=max_text_w,
        font_name="Helvetica-Bold",
        font_size=5.8,
        line_h=6.0,
        max_lines=3,
    )

    # Small gap below title.
    details_top = after_title_y - 1.5
    available_h = details_top - y - inner_pad - 4.0

    c.setFillColor(colors.HexColor("#111827"))

    draw_label_value_lines(
        c,
        note_detail_lines(note),
        tx,
        details_top,
        max_width_pt=max_text_w,
        max_height_pt=available_h,
        start_size=5.15,
        min_size=3.7,
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

    pad = 1.4 * mm
    gap = 1.7 * mm

    ix = x + pad
    iy = y + pad
    iw = w - 2 * pad
    ih = h - 2 * pad

    img_h = ih

    preferred_note_box_ratio = 2.28
    img_w = img_h * preferred_note_box_ratio

    max_image_total_w = iw * 0.62
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


def draw_cover_summary_table(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    summary: dict[str, Any],
) -> None:
    dark_green = colors.HexColor("#102f2a")
    gold = colors.HexColor("#c8a75a")
    pale = colors.HexColor("#f3ecd8")
    row_fill = colors.HexColor("#efe3bf")

    c.saveState()

    c.setFillColor(pale)
    c.setStrokeColor(gold)
    c.setLineWidth(1.3)
    c.roundRect(x, y, w, h, 8, stroke=1, fill=1)

    header_h = 18
    c.setFillColor(dark_green)
    c.roundRect(x + 6, y + h - header_h - 6, w - 12, header_h, 5, stroke=0, fill=1)

    c.setFillColor(colors.HexColor("#f4e7bf"))
    c.setFont("Helvetica-Bold", 9.2)
    c.drawCentredString(x + w / 2, y + h - header_h / 2 - 9.2, "KOGU KOLLEKTSIOONI KOKKUVÕTE")

    rows = [
        ("Kirjeid kokku", str(summary["total_notes"])),
        ("Hinnastatud kirjeid", str(summary["priced_count"])),
        ("Hinnata kirjeid", str(summary["missing_price_count"])),
        ("Toorhindade summa", f"{summary['raw_total']:.2f} €"),
        ("Saatmiskulude summa", f"{summary['shipping_total']:.2f} €"),
        ("Kokku koos saatmisega", f"{summary['total_with_shipping']:.2f} €"),
        ("Keskmine toorhind", f"{summary['avg_raw']:.2f} €"),
        ("Koostatud", summary["created_at"].strftime("%Y-%m-%d %H:%M")),
    ]

    inner_x = x + 10
    inner_w = w - 20
    table_top = y + h - header_h - 14
    table_bottom = y + 10
    table_h = table_top - table_bottom
    row_h = table_h / len(rows)

    for i, (label, value) in enumerate(rows):
        ry = table_top - (i + 1) * row_h

        if i % 2 == 0:
            c.setFillColor(row_fill)
            c.rect(inner_x, ry, inner_w, row_h, stroke=0, fill=1)

        c.setStrokeColor(colors.HexColor("#d1b96c"))
        c.setLineWidth(0.3)
        c.line(inner_x, ry, inner_x + inner_w, ry)

        c.setFillColor(dark_green)
        c.setFont("Helvetica-Bold", 8.6)
        c.drawString(inner_x + 5, ry + row_h / 2 - 3.0, label)

        c.setFillColor(colors.HexColor("#4b3718"))
        c.setFont("Helvetica-Bold", 8.8)
        c.drawRightString(inner_x + inner_w - 5, ry + row_h / 2 - 3.0, value)

    c.restoreState()


def draw_title_page(
    c: canvas.Canvas,
    notes: list[Note],
    page_w: float,
    page_h: float,
    title_money_image: Optional[str],
) -> None:
    summary = compute_inventory_summary(notes)

    cream = colors.HexColor("#eee8d8")
    dark_green = colors.HexColor("#102f2a")
    gold = colors.HexColor("#b9923c")
    pale_gold = colors.HexColor("#e8d39a")
    brown = colors.HexColor("#4b3718")

    c.setFillColor(cream)
    c.rect(0, 0, page_w, page_h, stroke=0, fill=1)

    margin = 9 * mm
    c.setStrokeColor(gold)
    c.setLineWidth(1.4)
    c.roundRect(margin, margin, page_w - 2 * margin, page_h - 2 * margin, 10, stroke=1, fill=0)
    c.setStrokeColor(colors.HexColor("#d7c48f"))
    c.setLineWidth(0.8)
    c.roundRect(margin + 4, margin + 4, page_w - 2 * (margin + 4), page_h - 2 * (margin + 4), 9, stroke=1, fill=0)

    c.setFillColor(dark_green)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(page_w / 2, page_h - 21 * mm, "Ostaponni paberrahade kataloog")

    c.setFillColor(brown)
    c.setFont("Helvetica", 10.5)
    c.drawCentredString(page_w / 2, page_h - 27 * mm, "Kollektsioon, hinnad ja ülevaade")

    image_box_w = page_w - 28 * mm
    image_box_h = 96 * mm
    image_box_x = (page_w - image_box_w) / 2
    image_box_y = page_h - 36 * mm - image_box_h

    c.setFillColor(colors.HexColor("#f8f2df"))
    c.setStrokeColor(gold)
    c.setLineWidth(1.3)
    c.roundRect(image_box_x, image_box_y, image_box_w, image_box_h, 8, stroke=1, fill=1)

    c.setStrokeColor(dark_green)
    c.setLineWidth(0.8)
    c.roundRect(image_box_x + 4, image_box_y + 4, image_box_w - 8, image_box_h - 8, 6, stroke=1, fill=0)

    draw_image_plain_fit(
        c,
        title_money_image,
        image_box_x + 7,
        image_box_y + 7,
        image_box_w - 14,
        image_box_h - 14,
    )

    table_w = page_w - 44 * mm
    table_h = 76 * mm
    table_x = (page_w - table_w) / 2
    table_y = image_box_y - table_h - 14 * mm

    draw_cover_summary_table(c, table_x, table_y, table_w, table_h, summary)

    c.setFillColor(pale_gold)
    c.setStrokeColor(gold)
    c.setLineWidth(0.6)
    c.roundRect(page_w / 2 - 38 * mm, 16 * mm, 76 * mm, 10 * mm, 4, stroke=1, fill=1)

    c.setFillColor(dark_green)
    c.setFont("Helvetica-Bold", 7.8)
    c.drawCentredString(
        page_w / 2,
        19.2 * mm,
        f"Genereeritud {summary['created_at'].strftime('%Y-%m-%d %H:%M')}"
    )


def make_pdf(
    notes: list[Note],
    pdf_path: Path,
    per_page: int = 8,
    title_money_image: Optional[str] = None,
) -> None:
    page_size = portrait(A4)
    c = canvas.Canvas(str(pdf_path), pagesize=page_size)

    page_w, page_h = page_size

    draw_title_page(c, notes, page_w, page_h, title_money_image)

    note_pages = (len(notes) + per_page - 1) // per_page
    total_pages = 1 + note_pages

    if note_pages > 0:
        c.showPage()

    margin = 8 * mm
    gap = 3 * mm
    rows = per_page

    cell_w = page_w - 2 * margin
    cell_h = (page_h - 2 * margin - (rows - 1) * gap) / rows

    for idx, note in enumerate(notes):
        pos = idx % per_page

        if idx > 0 and pos == 0:
            current_page = 2 + idx // per_page
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.HexColor("#5b6470"))
            c.drawCentredString(page_w / 2, 5 * mm, f"Page {current_page - 1} / {total_pages}")
            c.showPage()

        row = pos
        x = margin
        y = page_h - margin - (row + 1) * cell_h - row * gap

        draw_note_card(c, note, idx, x, y, cell_w, cell_h)

    if note_pages > 0:
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
    parser.add_argument("--user", default="", help="Cashroll username.")
    parser.add_argument("--password", default="", help="Cashroll password. Safer: use --password-stdin.")
    parser.add_argument("--password-stdin", action="store_true", help="Ask password interactively.")
    parser.add_argument("--no-value-debug", action="store_true", help="Disable console debug lines for currency/value retrieval.")
    parser.add_argument("--no-cost-debug", action="store_true", help="Disable console debug lines for item price/shipping.")
    parser.add_argument("--top", type=int, default=100, help="How many most expensive notes to show in the console table.")
    parser.add_argument("--title-money-image", default="", help="Premade title-page money image, e.g. ostaponn_money.png")
    args = parser.parse_args()

    ensure_dirs()

    if not PLACEHOLDER_IMAGE.exists():
        print()
        print(f"WARNING: Placeholder image not found: {PLACEHOLDER_IMAGE}")
        print("Save the banknote placeholder image as 'missing_note.png' next to this script.")
        print()

    title_money_image = find_title_money_image(args.title_money_image)
    if not title_money_image:
        print()
        print("WARNING: Title money image not found.")
        print("Save it as 'ostaponn_money.png' next to this script, or use:")
        print('  --title-money-image "ostaponn(1).png"')
        print()

    session = requests.Session()
    session.headers.update(HEADERS)

    password = args.password
    if args.password_stdin:
        password = getpass.getpass("Cashroll password: ")

    if args.user:
        if not password:
            password = getpass.getpass("Cashroll password: ")

        ok = login(session, args.user, password)

        if not ok:
            print()
            print("WARNING: login did not confirm a session user.")
            print("Continuing anyway, but price/shipping fields may be missing.")
            print()
    else:
        print("No --user supplied. Running without login; price/shipping fields will probably be missing.")

    session_info = get_session_info(session)
    print(f"Session info before table fetch: {json.dumps(session_info, ensure_ascii=False)}")

    print(f"Fetching table JSON: {TABLE_URL}")
    rows = fetch_table(session)
    print(f"Rows found: {len(rows)}")

    if rows:
        print(f"First row length: {len(rows[0])}")
        if len(rows[0]) > 17:
            print("Logged-in price/shipping columns appear to exist: row[16], row[17]")
        else:
            print("Price/shipping columns not visible. You are probably not logged in.")

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
                debug_costs=not args.no_cost_debug,
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

    print_inventory_stats(notes, top_n=args.top)

    print(f"Creating PDF: {args.out}")
    make_pdf(
        notes,
        Path(args.out),
        per_page=args.per_page,
        title_money_image=title_money_image,
    )

    print()
    print("Done.")
    print(f"Notes: {len(notes)}")
    print(f"JSON: {JSON_PATH}")
    print(f"Images: {IMG_DIR}")
    print(f"Debug: {DEBUG_DIR}")
    print(f"PDF: {args.out}")


if __name__ == "__main__":
    main()