"""
Solunar RSS feed for Palihan, Yogyakarta.

Source:
https://tides4fishing.com/id/yogyakarta/palihan

Solunar activity is read directly from the fish icons:

    0 active fish -> rendah
    1 active fish -> sedang
    2 active fish -> tinggi
    3 active fish -> sangat tinggi
"""

import argparse
import datetime
import re
import traceback
import os
from collections import Counter
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

URL = "https://tides4fishing.com/id/yogyakarta/palihan"

# Public URL where GitHub Pages serves the generated images.
# Set this in GitHub Actions. Example:
#   https://vannzee.github.io/solunar-feed/images
IMAGE_BASE_URL = os.environ.get(
    "IMAGE_BASE_URL",
    "",
).rstrip("/")

IMAGE_DIR = "images"

TZ = ZoneInfo("Asia/Jakarta")
UTC = datetime.timezone.utc

H1 = datetime.timedelta(hours=1)
M30 = datetime.timedelta(minutes=30)

HARI_INDO = [
    "Sen",
    "Sel",
    "Rab",
    "Kam",
    "Jum",
    "Sab",
    "Min",
]

BULAN_INDO = [
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Mei",
    "Jun",
    "Jul",
    "Agt",
    "Sep",
    "Okt",
    "Nov",
    "Des",
]

MONTHS_EN = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

# Correct fish mapping.
LEVELS_ID = [
    "rendah",         # 0 fish
    "sedang",         # 1 fish
    "tinggi",         # 2 fish
    "sangat tinggi",  # 3 fish
]


# ============================================================
# STATUS / TEXT MAPPING
# ============================================================

STATUS_MAP = {
    "very high": "sangat tinggi",
    "very high activity": "sangat tinggi",

    "high": "tinggi",
    "high activity": "tinggi",

    "average": "sedang",
    "average activity": "sedang",

    "low": "rendah",
    "low activity": "rendah",

    # Indonesian
    "sangat tinggi": "sangat tinggi",
    "tinggi": "tinggi",
    "sedang": "sedang",
    "rendah": "rendah",
}


LEVEL_PATTERN = (
    r"very high activity|"
    r"very high|"
    r"high activity|"
    r"average activity|"
    r"low activity|"
    r"sangat tinggi|"
    r"tinggi|"
    r"sedang|"
    r"rendah|"
    r"high|"
    r"average|"
    r"low"
)

LEVEL_ONLY = re.compile(
    r"\b(" + LEVEL_PATTERN + r")\b",
    re.I,
)


# ============================================================
# TABLE REGEX
# ============================================================

DAYROW = re.compile(
    r"^(\d{1,2})\s+"
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b",
    re.I,
)

COEF_CELL = re.compile(
    r"^\d{1,3}\s+(?:"
    + LEVEL_PATTERN
    + r")$",
    re.I,
)


# ============================================================
# GENERAL HTML HELPERS
# ============================================================

def flatten(html: str) -> str:
    """
    Convert HTML into normalized text.
    """

    if "</" in html:
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        for tag in soup(["script", "style"]):
            tag.decompose()

        html = soup.get_text(" ")

    return re.sub(
        r"\s+",
        " ",
        html,
    ).strip()


# ============================================================
# MONTH / YEAR
# ============================================================

def month_year_of_table(
    text: str,
    today: datetime.date,
):
    """
    Determine the month/year of the monthly tide table.
    """

    start = text.lower().find(
        "tide table"
    )

    scope = (
        text[start:start + 6000]
        if start != -1
        else text[:6000]
    )

    hits = re.findall(
        r"\b("
        + "|".join(MONTHS_EN)
        + r")\s*,?\s*(20\d\d)\b",
        scope,
        re.I,
    )

    if not hits:
        return today.year, today.month

    counts = Counter(
        (
            month.capitalize(),
            year,
        )
        for month, year in hits
    )

    (month, year), _ = counts.most_common(1)[0]

    return (
        int(year),
        MONTHS_EN.index(month) + 1,
    )


# ============================================================
# COEFFICIENT PARSER
# ============================================================

def parse_coefficients(
    html: str,
    today: datetime.date,
):
    """
    Extract tide coefficient from the monthly table.
    """

    text = flatten(html)

    year, month = month_year_of_table(
        text,
        today,
    )

    out = {}

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for tr in soup.find_all("tr"):

        row_text = " ".join(
            tr.get_text(" ").split()
        )

        day_match = DAYROW.match(
            row_text
        )

        if not day_match:
            continue

        day_number = int(
            day_match.group(1)
        )

        cells = tr.find_all(
            ["td", "th"]
        )

        for cell in cells:

            cell_text = " ".join(
                cell.get_text(" ").split()
            )

            # Example:
            #
            # 72 high
            # 54 average
            #
            match = re.match(
                r"^(\d{1,3})\s+(.+)$",
                cell_text,
                re.I,
            )

            if not match:
                continue

            coefficient = match.group(1)
            status_raw = match.group(2).lower()

            if not LEVEL_ONLY.search(
                status_raw
            ):
                continue

            status_match = LEVEL_ONLY.search(
                status_raw
            )

            status = STATUS_MAP.get(
                status_match.group(1).lower(),
                status_match.group(1).lower(),
            )

            try:
                date = datetime.date(
                    year,
                    month,
                    day_number,
                )

            except ValueError:
                continue

            out.setdefault(
                date,
                f"{coefficient} ({status})",
            )

            break

    return out


# ============================================================
# SOLUNAR FISH PARSER
# ============================================================

def parse_fish_activity(cell):
    """
    Parse Tides4Fishing's fish icons.

    Actual HTML:

        <span class="icon-ic_pez_leyenda"></span>

            = active fish

        <span class="icon-ic_pez_leyenda2 noprint"></span>

            = grey/inactive fish

    There are always three fish slots.

    Mapping:

        0 fish -> rendah
        1 fish -> sedang
        2 fish -> tinggi
        3 fish -> sangat tinggi
    """

    active_fish = len(
        cell.find_all(
            "span",
            class_="icon-ic_pez_leyenda",
        )
    )

    if active_fish >= 3:
        return "sangat tinggi"

    if active_fish == 2:
        return "tinggi"

    if active_fish == 1:
        return "sedang"

    return "rendah"


def parse_solunar(
    html: str,
    today: datetime.date,
):
    """
    Extract SOLUNAR ACTIVITY directly from the fish icons.

    We specifically search for:

        td.tabla_mareas_actividad

    rather than assuming the activity cell is a certain
    position relative to the coefficient cell.

    This is important because the activity cell has:

        rowspan="2"
    """

    out = {}
    sample = None

    if "</" not in html:
        return out, sample

    text = flatten(html)

    year, month = month_year_of_table(
        text,
        today,
    )

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for tr in soup.find_all("tr"):

        row_text = " ".join(
            tr.get_text(" ").split()
        )

        day_match = DAYROW.match(
            row_text
        )

        if not day_match:
            continue

        day_number = int(
            day_match.group(1)
        )

        # --------------------------------------------------------
        # IMPORTANT:
        #
        # Do NOT use "coefficient cell + 1".
        #
        # The solunar cell has rowspan="2".
        #
        # Instead find it by its exact class.
        # --------------------------------------------------------

        activity_cells = tr.find_all(
            "td",
            class_="tabla_mareas_actividad",
        )

        if not activity_cells:
            continue

        cell = activity_cells[0]

        if sample is None:
            sample = str(tr)[:5000]

        # --------------------------------------------------------
        # Count active fish.
        # --------------------------------------------------------

        active_fish = len(
            cell.find_all(
                "span",
                class_="icon-ic_pez_leyenda",
            )
        )

        # --------------------------------------------------------
        # Convert fish count to Indonesian level.
        # --------------------------------------------------------

        level = parse_fish_activity(
            cell
        )

        try:
            date = datetime.date(
                year,
                month,
                day_number,
            )

        except ValueError:
            continue

        out.setdefault(
            date,
            level,
        )

        print(
            f"[solunar] "
            f"{date.isoformat()} -> "
            f"{active_fish} fish -> "
            f"{level}"
        )

    return out, sample


# ============================================================
# SCREENSHOT TIDE TABLE
# ============================================================

def screenshot_tide_table(
    output_path,
):
    """
    Open the live Tides4Fishing page in Chromium and save the
    complete rendered monthly tide table as a PNG.

    The complete table is identified by:

        #tabla_mareas

    Browser viewport matches the portrait QHD monitor:

        1440 x 2560

    Browser zoom remains at 100%.
    """

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
        exist_ok=True,
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
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

            # ------------------------------------------------
            # Wait for the complete monthly table.
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Keep browser zoom at 100%.
            # ------------------------------------------------

            page.evaluate("""
                document.body.style.zoom = "100%";
            """)

            # Allow fonts, icons and images to finish loading.
            page.wait_for_timeout(3000)

            # ------------------------------------------------
            # Scroll the table into the viewport.
            #
            # The Tides4Fishing header is fixed/sticky and can
            # cover the first days of the table. We position the
            # table slightly below the top of the viewport.
            # ------------------------------------------------

            page.evaluate("""
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
            """)

            page.wait_for_timeout(2000)

            # ------------------------------------------------
            # Screenshot ONLY the complete table.
            # ------------------------------------------------

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
# DOWNLOAD PAGE
# ============================================================

def fetch_page(
    sample_file=None,
):
    """
    Download Tides4Fishing HTML.

    --sample can be used to test with a saved HTML file.
    """

    if sample_file:

        print(
            f"[scrape] Using sample: "
            f"{sample_file}"
        )

        with open(
            sample_file,
            encoding="utf-8",
        ) as file:
            return file.read()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/154.0.0.0 "
            "Safari/537.36"
        ),
        "Accept-Language": (
            "en-US,en;q=0.9"
        ),
        "Accept": (
            "text/html,"
            "application/xhtml+xml,"
            "application/xml;q=0.9,"
            "*/*;q=0.8"
        ),
    }

    try:

        response = requests.get(
            URL,
            headers=headers,
            timeout=30,
        )

        print(
            f"[scrape] HTTP "
            f"{response.status_code} "
            f"({len(response.text)} bytes)"
        )

        response.raise_for_status()

        return response.text

    except Exception:

        print(
            "[scrape] ERROR:"
        )

        traceback.print_exc()

        return None


# ============================================================
# ASTRONOMICAL FALLBACK
# ============================================================

def compute_days(
    today: datetime.date,
    n: int = 14,
):
    """
    Calculate moon/sun events.

    These are used for the RSS major/minor periods.

    Solunar activity itself comes from Tides4Fishing.
    """

    import ephem

    observer = ephem.Observer()

    observer.lat = "-7.91"
    observer.lon = "110.07"
    observer.elevation = 5

    days = []

    for i in range(n):

        date = (
            today
            + datetime.timedelta(
                days=i
            )
        )

        start = datetime.datetime.combine(
            date,
            datetime.time(0),
            tzinfo=TZ,
        )

        end = (
            start
            + datetime.timedelta(days=1)
        )

        observer.date = (
            start
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

        moon = ephem.Moon()
        sun = ephem.Sun()

        def event(
            function,
            body,
        ):

            try:

                event_time = function(
                    body
                )

            except (
                ephem.NeverUpError,
                ephem.AlwaysUpError,
            ):

                return None

            dt = (
                ephem.Date(
                    event_time
                )
                .datetime()
                .replace(
                    tzinfo=UTC
                )
                .astimezone(TZ)
            )

            if start <= dt < end:
                return dt

            return None

        transit = event(
            observer.next_transit,
            moon,
        )

        anti = event(
            observer.next_antitransit,
            moon,
        )

        rise = event(
            observer.next_rising,
            moon,
        )

        moon_set = event(
            observer.next_setting,
            moon,
        )

        sunrise = event(
            observer.next_rising,
            sun,
        )

        sunset = event(
            observer.next_setting,
            sun,
        )

        # Approximate moon phase distance.
        observer.date = (
            start
            .astimezone(UTC)
            .replace(tzinfo=None)
        )

        try:

            phase_dates = [
                ephem.previous_new_moon(
                    observer.date
                ),
                ephem.next_new_moon(
                    observer.date
                ),
                ephem.previous_full_moon(
                    observer.date
                ),
                ephem.next_full_moon(
                    observer.date
                ),
            ]

            reference = float(
                observer.date
            )

            distance = min(
                abs(
                    reference
                    - float(p)
                )
                for p in phase_dates
            )

        except Exception:

            distance = 10

        days.append(
            {
                "date": date,
                "dist": distance,
                "transit": transit,
                "anti": anti,
                "rise": rise,
                "set": moon_set,
                "sunrise": sunrise,
                "sunset": sunset,
            }
        )

    return days


# ============================================================
# FALLBACK SOLUNAR ESTIMATE
# ============================================================

def estimate_solunar(day):
    """
    Astronomical fallback only.

    Normally this will NOT be used because the real
    Tides4Fishing fish activity is parsed from the page.
    """

    distance = day["dist"]

    if distance <= 2:
        base = 2

    elif distance <= 5.5:
        base = 1

    else:
        base = 0

    periods = [
        (t - H1, t + H1)
        for t in (
            day["transit"],
            day["anti"],
        )
        if t
    ]

    periods += [
        (t - M30, t + M30)
        for t in (
            day["rise"],
            day["set"],
        )
        if t
    ]

    sun_periods = [
        (t - M30, t + M30)
        for t in (
            day["sunrise"],
            day["sunset"],
        )
        if t
    ]

    bonus = any(
        a0 < b1 and b0 < a1
        for a0, a1 in periods
        for b0, b1 in sun_periods
    )

    return min(
        3,
        base + (
            1
            if bonus
            else 0
        ),
    )


# ============================================================
# TIME FORMATTING
# ============================================================

def _hm(t):

    if not t:
        return "-"

    return t.strftime(
        "%H:%M"
    )


def _win(
    t,
    delta,
):

    if not t:
        return "-"

    return (
        f"{_hm(t - delta)} - "
        f"{_hm(t + delta)}"
    )


# ============================================================
# RSS ENTRY
# ============================================================

def build_entry(
    i,
    day,
    coefficient,
    solunar,
    from_site,
    image_url=None,
):

    date = day["date"]

    if i == 0:

        label = "Hari ini"

    else:

        label = (
            f"{HARI_INDO[date.weekday()]}, "
            f"{date.day:02d} "
            f"{BULAN_INDO[date.month]}"
        )

    major = (
        f"Major: "
        f"{_hm(day['transit'])} & "
        f"{_hm(day['anti'])}"
    )

    if from_site:

        solunar_text = solunar

        solunar_note = (
            "data langsung dari "
            "Tides4Fishing"
        )

    else:

        solunar_text = (
            f"≈{solunar}"
        )

        solunar_note = (
            "perkiraan lokal karena "
            "data situs tidak terbaca"
        )

    title = (
        f"{label} | "
        f"Koef {coefficient or '-'} · "
        f"Aktivitas Ikan {solunar_text} | "
        f"{major}"
    )

    image_html = ""

    if image_url:
        image_html = (
            "<p>"
            f"<img src=\"{image_url}\" "
            "alt=\"Tabel pasang surut dan aktivitas ikan Palihan\" "
            "style=\"max-width:100%;height:auto;\">"
            "</p>"
        )

    description = (
        image_html
        +
        "<table border='1' "
        "cellpadding='4' "
        "cellspacing='0'>"

        "<tr>"
        "<th>Koefisien pasang surut</th>"
        "<th>Aktivitas Ikan</th>"
        "</tr>"

        "<tr>"
        f"<td>{coefficient or '-'}</td>"
        f"<td>{solunar_text}</td>"
        "</tr>"

        "</table>"

        f"<br><i>{solunar_note}</i>"
        "<br><br>"

        "<b>Waktu Utama (Major):</b>"
        "<br>"

        f"• {_win(day['transit'], H1)}"
        "<br>"

        f"• {_win(day['anti'], H1)}"
        "<br><br>"

        "<b>Waktu Tambahan (Minor):</b>"
        "<br>"

        f"• {_win(day['rise'], M30)} "
        "(Terbit)"
        "<br>"

        f"• {_win(day['set'], M30)} "
        "(Terbenam)"
    )

    return title, description


# ============================================================
# WRITE RSS
# ============================================================

def write_feed(
    path,
    days,
    coefficients,
    site_solunar,
    now_time,
    image_url=None,
):

    from feedgen.feed import FeedGenerator

    feed = FeedGenerator()

    feed.title(
        "Aktivitas Ikan Palihan"
    )

    feed.link(
        href=URL,
        rel="alternate",
    )

    feed.description(
        "Prediksi aktivitas ikan "
        "Palihan: koefisien pasang surut "
        "+ aktivitas ikan"
    )

    feed.language("id")

    for i, day in enumerate(days):

        date = day["date"]

        from_site = (
            date in site_solunar
        )

        if from_site:

            solunar = site_solunar[
                date
            ]

        else:

            solunar = LEVELS_ID[
                estimate_solunar(day)
            ]

        title, description = (
            build_entry(
                i,
                day,
                coefficients.get(date),
                solunar,
                from_site,
                image_url=image_url,
            )
        )

        entry = feed.add_entry()

        entry.id(
            f"palihan-{date.isoformat()}"
        )

        entry.title(
            title
        )

        entry.link(
            href=URL
        )

        entry.description(
            description
        )

        entry.pubDate(
            now_time
            - datetime.timedelta(
                hours=i
            )
        )

    feed.rss_file(
        path,
        pretty=True,
    )

    print(
        f"[feed] {path} ditulis"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--sample",
        help=(
            "Use local HTML instead "
            "of downloading the website."
        ),
    )

    args = parser.parse_args()

    now_time = datetime.datetime.now(
        TZ
    )

    today = now_time.date()

    print(
        f"[main] Today: "
        f"{today.isoformat()}"
    )

    # --------------------------------------------------------
    # Download HTML
    # --------------------------------------------------------

    raw = fetch_page(
        args.sample
    )

    coefficients = {}
    site_solunar = {}

    if raw:

        # ----------------------------------------------------
        # Parse coefficient
        # ----------------------------------------------------

        coefficients = (
            parse_coefficients(
                raw,
                today,
            )
        )

        print(
            f"[scrape] "
            f"Coefficient days: "
            f"{len(coefficients)}"
        )

        # ----------------------------------------------------
        # Parse actual fish activity
        # ----------------------------------------------------

        site_solunar, sample = (
            parse_solunar(
                raw,
                today,
            )
        )

        print(
            f"[scrape] "
            f"Aktivitas ikan days from site: "
            f"{len(site_solunar)}"
        )

        if not site_solunar:

            print(
                "[scrape] WARNING: "
                "No solunar activity was found."
            )

            if sample:

                print(
                    "[scrape] Sample row:"
                )

                print(
                    sample
                )

    else:

        print(
            "[scrape] WARNING: "
            "Could not download website."
        )

    # --------------------------------------------------------
    # Calculate astronomical events
    # --------------------------------------------------------

    days = compute_days(
        today,
        14,
    )

    # --------------------------------------------------------
    # Screenshot the rendered monthly tide table
    # --------------------------------------------------------

    image_url = None

    if IMAGE_BASE_URL:

        os.makedirs(
            IMAGE_DIR,
            exist_ok=True,
        )

        image_filename = (
            f"palihan-{today.year:04d}-"
            f"{today.month:02d}.png"
        )

        image_path = os.path.join(
            IMAGE_DIR,
            image_filename,
        )

        if screenshot_tide_table(
            image_path
        ):
            image_url = (
                f"{IMAGE_BASE_URL}/"
                f"{image_filename}"
            )

    else:

        print(
            "[screenshot] IMAGE_BASE_URL is not set; "
            "RSS will contain text only."
        )

    # --------------------------------------------------------
    # Generate RSS
    # --------------------------------------------------------

    write_feed(
        "palihan.xml",
        days,
        coefficients,
        site_solunar,
        now_time,
        image_url=image_url,
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
