import argparse
import datetime
import os
import re
import traceback
from collections import Counter
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator


URL = "https://tides4fishing.com/id/yogyakarta/palihan"

TIMEZONE = "Asia/Jakarta"

IMAGE_DIR = "images"

IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")


# ============================================================
# GET TIDES4FISHING PAGE
# ============================================================

def get_page():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/154.0.0.0 Safari/537.36"
        )
    }

    response = requests.get(
        URL,
        headers=headers,
        timeout=60,
    )

    response.raise_for_status()

    return response.text


# ============================================================
# PARSE FISH ACTIVITY
# ============================================================

def get_fish_activity(cell):
    """
    Count fish icons.

    Active:
        icon-ic_pez_leyenda

    Inactive / grey:
        icon-ic_pez_leyenda2
    """

    active = len(
        cell.select(
            "span.icon-ic_pez_leyenda"
        )
    )

    inactive = len(
        cell.select(
            "span.icon-ic_pez_leyenda2"
        )
    )

    # Remove inactive icons from the count.
    # The actual activity level is based on active fish icons.
    count = active

    if count >= 3:
        return "sangat tinggi"

    if count == 2:
        return "tinggi"

    if count == 1:
        return "sedang"

    return "rendah"


# ============================================================
# PARSE TIDE TABLE
# ============================================================

def parse_tides(html):
    soup = BeautifulSoup(html, "html.parser")

    table = soup.select_one("#tabla_mareas")

    if not table:
        raise RuntimeError(
            "Table #tabla_mareas tidak ditemukan."
        )

    rows = []

    current_date = None

    for tr in table.select("tr"):

        text = " ".join(
            tr.stripped_strings
        )

        if not text:
            continue

        # ----------------------------------------------------
        # DATE
        # ----------------------------------------------------

        date_match = re.search(
            r"(\d{1,2})[/-](\d{1,2})",
            text
        )

        if date_match:
            day = int(date_match.group(1))
            month = int(date_match.group(2))

            current_date = (
                day,
                month
            )

        # ----------------------------------------------------
        # TIME
        # ----------------------------------------------------

        time_match = re.search(
            r"\b(\d{1,2}):(\d{2})\b",
            text
        )

        if not time_match:
            continue

        time_value = (
            f"{int(time_match.group(1)):02d}:"
            f"{time_match.group(2)}"
        )

        # ----------------------------------------------------
        # HEIGHT
        # ----------------------------------------------------

        height_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*m\b",
            text,
            re.IGNORECASE
        )

        height = None

        if height_match:
            height = height_match.group(1).replace(
                ",",
                "."
            )

        # ----------------------------------------------------
        # FISH ACTIVITY
        # ----------------------------------------------------

        fish_activity = get_fish_activity(tr)

        rows.append(
            {
                "date": current_date,
                "time": time_value,
                "height": height,
                "fish_activity": fish_activity,
            }
        )

    return rows


# ============================================================
# SCREENSHOT TIDE TABLE
# ============================================================

def screenshot_tide_table(output_path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "[screenshot] Playwright is not installed; "
            "skipping table screenshot."
        )
        return False

    os.makedirs(
        os.path.dirname(output_path) or ".",
        exist_ok=True
    )

    try:
        with sync_playwright() as p:

            browser = p.chromium.launch(
                headless=True
            )

            page = browser.new_page(
                viewport={
                    "width": 1440,
                    "height": 2560,
                },
                device_scale_factor=1,
            )

            print(
                f"[screenshot] Opening {URL}"
            )

            page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            table = page.locator(
                "#tabla_mareas"
            )

            table.wait_for(
                state="visible",
                timeout=60000,
            )

            print(
                "[screenshot] Found #tabla_mareas"
            )

            page.evaluate(
                """
                document.body.style.zoom = "100%";
                """
            )

            page.wait_for_timeout(3000)

            page.evaluate(
                """
                const table =
                    document.querySelector("#tabla_mareas");

                if (table) {
                    const rect =
                        table.getBoundingClientRect();

                    const absoluteTop =
                        rect.top + window.scrollY;

                    window.scrollTo({
                        top: Math.max(
                            0,
                            absoluteTop - 100
                        ),
                        behavior: "instant"
                    });
                }
                """
            )

            page.wait_for_timeout(2000)

            table.screenshot(
                path=output_path,
                animations="disabled",
            )

            browser.close()

        print(
            f"[screenshot] Saved {output_path}"
        )

        return True

    except Exception:
        print(
            "[screenshot] ERROR:"
        )

        traceback.print_exc()

        return False


# ============================================================
# BUILD RSS ENTRY
# ============================================================

def build_entry(
    fg,
    day,
    coefficients,
    site_solunar,
    now_time,
    image_url=None,
    image_path=None,
):

    entry = fg.add_entry()

    date_value = day.get(
        "date",
        now_time.date()
    )

    title = (
        f"Palihan - "
        f"{date_value.strftime('%d-%m-%Y')}"
    )

    entry.title(title)

    entry.id(
        f"{URL}#{date_value.isoformat()}"
    )

    entry.link(
        href=URL,
        rel="alternate"
    )

    entry.published(
        now_time
    )

    # --------------------------------------------------------
    # IMAGE HTML
    # --------------------------------------------------------

    image_html = ""

    if image_url:

        image_html = (
            "<p>"
            f"<img src=\"{image_url}\" "
            "alt=\"Tabel pasang surut dan aktivitas ikan Palihan\" "
            "style=\"max-width:100%;height:auto;\">"
            "</p>"
        )

    # --------------------------------------------------------
    # RSS ENCLOSURE
    # --------------------------------------------------------

    if image_url and image_path:

        try:

            image_size = os.path.getsize(
                image_path
            )

            entry.enclosure(
                url=image_url,
                length=image_size,
                type="image/png",
            )

            print(
                "[rss] Added image enclosure:"
                f" {image_url}"
            )

            print(
                "[rss] Image size:"
                f" {image_size} bytes"
            )

        except OSError as exc:

            print(
                "[rss] WARNING: "
                f"Could not read image size: {exc}"
            )

    # --------------------------------------------------------
    # TIDE TABLE
    # --------------------------------------------------------

    table_html = (
        "<table border='1' "
        "cellpadding='4' "
        "cellspacing='0'>"
        "<tr>"
        "<th>Jam</th>"
        "<th>Tinggi</th>"
        "<th>Aktivitas ikan</th>"
        "</tr>"
    )

    for item in day.get("tides", []):

        time_value = item.get(
            "time",
            "-"
        )

        height = item.get(
            "height",
            "-"
        )

        fish_activity = item.get(
            "fish_activity",
            "rendah"
        )

        table_html += (
            "<tr>"
            f"<td>{time_value}</td>"
            f"<td>{height}</td>"
            f"<td>{fish_activity}</td>"
            "</tr>"
        )

    table_html += "</table>"

    # --------------------------------------------------------
    # SOLUNAR INFORMATION
    # --------------------------------------------------------

    solunar_html = ""

    if site_solunar:

        solunar_html = (
            "<p>"
            "<b>Aktivitas ikan:</b> "
            f"{site_solunar}"
            "</p>"
        )

    # --------------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------------

    description = (
        image_html
        +
        solunar_html
        +
        table_html
    )

    entry.description(
        description
    )

    return entry


# ============================================================
# WRITE RSS FEED
# ============================================================

def write_feed(
    output_path,
    days,
    coefficients,
    site_solunar,
    now_time,
    image_url=None,
    image_path=None,
):

    fg = FeedGenerator()

    fg.id(
        f"{URL}/rss"
    )

    fg.title(
        "Palihan - Pasang Surut & Aktivitas Ikan"
    )

    fg.author(
        {
            "name": "Vannzee"
        }
    )

    fg.link(
        href=URL,
        rel="alternate"
    )

    fg.link(
        href="https://vannzee.github.io/solunar-feed/palihan.xml",
        rel="self"
    )

    fg.description(
        "Informasi pasang surut dan aktivitas ikan "
        "Palihan, Yogyakarta."
    )

    fg.language("id")

    fg.lastBuildDate(
        now_time
    )

    # --------------------------------------------------------
    # ADD ENTRIES
    # --------------------------------------------------------

    for day in days:

        build_entry(
            fg=fg,
            day=day,
            coefficients=coefficients,
            site_solunar=site_solunar,
            now_time=now_time,
            image_url=image_url,
            image_path=image_path,
        )

    # --------------------------------------------------------
    # WRITE RSS
    # --------------------------------------------------------

    fg.rss_file(
        output_path,
        pretty=True,
    )

    print(
        f"[rss] Saved {output_path}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--debug",
        action="store_true",
    )

    args = parser.parse_args()

    now_time = datetime.datetime.now(
        ZoneInfo(TIMEZONE)
    )

    print(
        f"Current time: {now_time}"
    )

    # --------------------------------------------------------
    # DOWNLOAD PAGE
    # --------------------------------------------------------

    print(
        f"[page] Downloading {URL}"
    )

    html = get_page()

    print(
        f"[page] Downloaded {len(html)} bytes"
    )

    # --------------------------------------------------------
    # PARSE TIDES
    # --------------------------------------------------------

    try:

        parsed_rows = parse_tides(
            html
        )

        print(
            f"[parse] Parsed {len(parsed_rows)} rows"
        )

    except Exception:

        print(
            "[parse] ERROR:"
        )

        traceback.print_exc()

        parsed_rows = []

    # --------------------------------------------------------
    # GROUP BY DATE
    # --------------------------------------------------------

    days = []

    grouped = {}

    for row in parsed_rows:

        date_key = row.get(
            "date"
        )

        if not date_key:
            continue

        grouped.setdefault(
            date_key,
            []
        ).append(row)

    for date_key, tides in sorted(
        grouped.items()
    ):

        days.append(
            {
                "date": datetime.date(
                    now_time.year,
                    date_key[1],
                    date_key[0],
                ),
                "tides": tides,
            }
        )

    # --------------------------------------------------------
    # FALLBACK IF NOTHING PARSED
    # --------------------------------------------------------

    if not days:

        days = [
            {
                "date": now_time.date(),
                "tides": [],
            }
        ]

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    image_url = None
    image_path = None

    if IMAGE_BASE_URL:

        os.makedirs(
            IMAGE_DIR,
            exist_ok=True
        )

        image_filename = (
            f"palihan-"
            f"{now_time.year:04d}-"
            f"{now_time.month:02d}.png"
        )

        image_path = os.path.join(
            IMAGE_DIR,
            image_filename
        )

        if screenshot_tide_table(
            image_path
        ):

            image_url = (
                f"{IMAGE_BASE_URL}/"
                f"{image_filename}"
            )

            print(
                f"[image] URL: {image_url}"
            )

        else:

            image_path = None

    # --------------------------------------------------------
    # SOLUNAR
    # --------------------------------------------------------

    site_solunar = None

    # Keep this compatible with the existing feed.
    # If your existing parser provides a solunar value,
    # it can still be passed here.
    #
    # The fish activity in the table itself is generated
    # from the Tides4Fishing fish icons.

    # --------------------------------------------------------
    # WRITE RSS
    # --------------------------------------------------------

    write_feed(
        "palihan.xml",
        days,
        {},
        site_solunar,
        now_time,
        image_url=image_url,
        image_path=image_path,
    )


if __name__ == "__main__":
    main()
