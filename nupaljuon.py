#!/usr/bin/env python3

import csv
import re
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import matplotlib

matplotlib.use("TkAgg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup, Tag
from curl_cffi import requests


SELLER = "ostaponn"
HISTORY_FILE = Path("osta_inventory_history.csv")


def canonical_seller_page_url(start: int | None = None) -> str:
    query = {
        "fuseaction": "listing.seller",
        "id": "1000",
        "q[seller]": SELLER,
        "q[cat]": "1000",
    }

    if start is not None:
        query["start"] = str(start)

    return "https://www.osta.ee/?" + urlencode(query)


START_URL = canonical_seller_page_url(None)

ITEM_RE = re.compile(r"/?([^/]+)-(\d{6,})\.html(?:[?#].*)?$")
PRICE_RE = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s*€")
TOTAL_RE = re.compile(r"Aktiivsed müügid\s+(\d+)|(\d+)\s+tulemust", re.I)


def money_to_decimal(text: str) -> Decimal | None:
    match = PRICE_RE.search(text.replace("\xa0", " "))
    if not match:
        return None

    return Decimal(match.group(1).replace(",", "."))


def txt(x) -> str:
    return " ".join(x.get_text(" ", strip=True).replace("\xa0", " ").split())


def is_item_link(tag) -> bool:
    if not isinstance(tag, Tag) or tag.name != "a":
        return False

    href = tag.get("href", "")
    title = txt(tag)

    if not title:
        return False

    return bool(ITEM_RE.search(href))


def item_id_from_link(tag: Tag) -> str:
    href = tag.get("href", "")
    match = ITEM_RE.search(href)

    if not match:
        raise ValueError(f"Could not extract item ID from href: {href}")

    return match.group(2)


def fetch_html(session, url: str) -> str:
    response = session.get(
        url,
        impersonate="chrome",
        timeout=30,
        headers={
            "Accept-Language": "et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.osta.ee/",
        },
    )

    if response.status_code == 403:
        raise RuntimeError(
            "Got 403 Forbidden even with browser impersonation. "
            "Osta.ee may be temporarily blocking scraping from your IP."
        )

    response.raise_for_status()
    return response.text


def extract_expected_total(soup: BeautifulSoup) -> int | None:
    body = txt(soup)
    matches = TOTAL_RE.findall(body)

    nums = []
    for a, b in matches:
        if a:
            nums.append(int(a))
        if b:
            nums.append(int(b))

    return max(nums) if nums else None


def extract_items_from_page(soup: BeautifulSoup, page_url: str) -> dict[str, dict]:
    links = soup.find_all(is_item_link)
    items = {}

    for link in links:
        item_id = item_id_from_link(link)

        if item_id in items:
            continue

        title = txt(link)
        item_url = urljoin(page_url, link.get("href", ""))

        price = None

        for node in link.next_elements:
            if node is link:
                continue

            if isinstance(node, Tag) and is_item_link(node):
                break

            if isinstance(node, str):
                price = money_to_decimal(node)
                if price is not None:
                    break

        if price is None:
            print(f"WARNING: no price found: {title} | {item_url}")
            continue

        items[item_id] = {
            "title": title,
            "price": price,
            "url": item_url,
        }

    return items


def normalize_seller_page_url(url: str) -> str | None:
    parsed = urlparse(url)

    # Reject /en, /ru, and other language/path variants.
    if parsed.path not in ("", "/"):
        return None

    qs = parse_qs(parsed.query)

    if qs.get("fuseaction", [""])[0] != "listing.seller":
        return None

    if qs.get("q[seller]", [""])[0] != SELLER:
        return None

    start_raw = qs.get("start", [None])[0]

    if start_raw is None:
        return canonical_seller_page_url(None)

    try:
        start = int(start_raw)
    except ValueError:
        return None

    return canonical_seller_page_url(start)


def extract_next_page_urls(soup: BeautifulSoup, current_url: str) -> set[str]:
    urls = set()

    for a in soup.find_all("a", href=True):
        absolute = urljoin(current_url, a["href"])
        normalized = normalize_seller_page_url(absolute)

        if normalized is not None:
            urls.add(normalized)

    return urls


def save_history_point(total_value: Decimal, item_count: int, expected_count: int | None) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    file_exists = HISTORY_FILE.exists()

    with HISTORY_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(["timestamp", "total_value_eur", "item_count", "expected_count"])

        writer.writerow([
            timestamp,
            f"{total_value:.2f}",
            item_count,
            expected_count if expected_count is not None else "",
        ])

    print(f"Saved history point to {HISTORY_FILE}: {timestamp} | {total_value:.2f} €")


def load_history() -> tuple[list[datetime], list[float], list[int]]:
    timestamps = []
    values = []
    item_counts = []

    if not HISTORY_FILE.exists():
        return timestamps, values, item_counts

    with HISTORY_FILE.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            try:
                timestamps.append(datetime.fromisoformat(row["timestamp"]))
                values.append(float(row["total_value_eur"]))
                item_counts.append(int(row["item_count"]))
            except Exception as e:
                print(f"WARNING: skipping bad history row {row}: {e}")

    return timestamps, values, item_counts


def plot_history() -> None:
    timestamps, values, item_counts = load_history()

    if not timestamps:
        print("No history to plot yet.")
        return

    fig, ax = plt.subplots(figsize=(14, 7))  # 2:1 ratio

    fig.patch.set_facecolor("#101820")
    ax.set_facecolor("#16213e")

    ax.plot(
        timestamps,
        values,
        color="#00d4ff",
        linewidth=3,
        marker="o",
        markersize=7,
        markerfacecolor="#ffcc00",
        markeredgecolor="#ffffff",
        markeredgewidth=1.4,
        label="Inventory value",
    )

    ax.fill_between(
        timestamps,
        values,
        min(values) * 0.995 if values else 0,
        color="#00d4ff",
        alpha=0.16,
    )

    latest_value = values[-1]
    latest_time = timestamps[-1]
    latest_count = item_counts[-1] if item_counts else None

    title = f"Osta.ee inventory value for seller '{SELLER}'"
    subtitle = f"Latest: {latest_value:,.2f} €"

    if latest_count is not None:
        subtitle += f" | Items: {latest_count}"

    ax.set_title(
        f"{title}\n{subtitle}",
        fontsize=18,
        color="#ffffff",
        weight="bold",
        pad=20,
    )

    ax.set_xlabel("Run timestamp", fontsize=12, color="#d8e2dc", labelpad=12)
    ax.set_ylabel("Total inventory value (€)", fontsize=12, color="#d8e2dc", labelpad=12)

    ax.grid(True, color="#ffffff", alpha=0.16, linestyle="--", linewidth=0.8)

    ax.tick_params(axis="x", colors="#d8e2dc", labelsize=10)
    ax.tick_params(axis="y", colors="#d8e2dc", labelsize=10)

    for spine in ax.spines.values():
        spine.set_color("#d8e2dc")
        spine.set_alpha(0.35)

    ax.yaxis.set_major_formatter(lambda x, _: f"{x:,.0f} €")

    if len(timestamps) == 1:
        ax.scatter(
            timestamps,
            values,
            s=180,
            color="#ffcc00",
            edgecolors="#ffffff",
            linewidths=1.6,
            zorder=5,
        )
    else:
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M"))
        fig.autofmt_xdate(rotation=25)

    ax.annotate(
        f"{latest_value:,.2f} €",
        xy=(latest_time, latest_value),
        xytext=(12, 14),
        textcoords="offset points",
        color="#ffffff",
        fontsize=12,
        weight="bold",
        bbox=dict(
            boxstyle="round,pad=0.45",
            facecolor="#ff006e",
            edgecolor="#ffffff",
            alpha=0.9,
        ),
        arrowprops=dict(
            arrowstyle="->",
            color="#ffffff",
            lw=1.4,
        ),
    )

    ax.legend(
        loc="best",
        facecolor="#101820",
        edgecolor="#ffffff",
        labelcolor="#ffffff",
        framealpha=0.6,
    )

    plt.tight_layout()
    plt.show()


def main():
    session = requests.Session()

    to_visit = [START_URL]
    visited = set()
    all_items = {}
    expected_total = None

    while to_visit:
        url = to_visit.pop(0)

        if url in visited:
            continue

        visited.add(url)
        print(f"Fetching page {len(visited)}: {url}")

        html = fetch_html(session, url)
        soup = BeautifulSoup(html, "html.parser")

        if expected_total is None:
            expected_total = extract_expected_total(soup)

        page_items = extract_items_from_page(soup, url)
        print(f"  Found {len(page_items)} items on this page")

        all_items.update(page_items)

        for next_url in sorted(extract_next_page_urls(soup, url)):
            if next_url not in visited and next_url not in to_visit:
                to_visit.append(next_url)

        time.sleep(0.8)

    total = sum(item["price"] for item in all_items.values())

    print()
    print(f"Pages fetched: {len(visited)}")
    print(f"Unique items found: {len(all_items)}")

    if expected_total is not None:
        print(f"Expected active listings: {expected_total}")

    print(f"Total inventory value: {total:.2f} €")

    if expected_total is not None and len(all_items) != expected_total:
        print()
        print("WARNING: item count does not match expected active listings.")
        print("Some items may have ended/started while scraping, or Osta.ee changed the page HTML.")

    print()
    print("Top 20 most expensive items:")
    for item in sorted(all_items.values(), key=lambda x: x["price"], reverse=True)[:20]:
        print(f'{item["price"]:>8.2f} € | {item["title"]} | {item["url"]}')

    print()
    save_history_point(total, len(all_items), expected_total)
    plot_history()


if __name__ == "__main__":
    main()