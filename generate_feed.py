"""
Solunar Palihan - RSS generator.

Generates:
    palihan.xml

The feed contains:
    - tidal coefficient
    - solunar fish activity
    - major solunar periods
    - minor solunar periods

Solunar activity mapping:

    grey / empty fish -> rendah
    1 fish             -> sedang
    2 fish             -> tinggi
    3 fish             -> sangat tinggi

Usage:

    python generate_feed.py

For testing with a saved HTML page:

    python generate_feed.py --sample page.html
"""

import argparse
import datetime
import re
import traceback
from collections import Counter
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

URL = "https://tides4fishing.com/id/yogyakarta/palihan"

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

# Index = number of active fish.
LEVELS_ID = [
    "rendah",
    "sedang",
    "tinggi",
    "sangat tinggi",
]


# ---------------------------------------------------------------------------
# ACTIVITY MAPPINGS
# ---------------------------------------------------------------------------

STATUS_MAP = {
    # English
    "very high": "sangat tinggi",
    "very high activity": "sangat tinggi",

    "high": "tinggi",
    "high activity": "tinggi",

    "average": "sedang",
    "average activity": "sedang",

    "low": "rendah",
    "low activity": "rendah",

    # Spanish / other possible Tides4Fishing translations
    "muy alta": "sangat tinggi",
    "muy alta actividad": "sangat tinggi",

    "alta": "tinggi",
    "alta actividad": "tinggi",

    "media": "sedang",
    "actividad media": "sedang",

    "baja": "rendah",
    "baja actividad": "rendah",

    # Indonesian
    "sangat tinggi": "sangat tinggi",
    "sangat tinggi aktivitas": "sangat tinggi",

    "tinggi": "tinggi",
    "tinggi aktivitas": "tinggi",

    "sedang": "sedang",
    "sedang aktivitas": "sedang",

    "rendah": "rendah",
    "rendah aktivitas": "rendah",
}


LEVEL_PATTERN = (
    r"very high activity|"
    r"very high|"
    r"high activity|"
    r"average activity|"
    r"low activity|"
    r"muy alta|"
    r"alta|"
    r"media|"
    r"baja|"
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


# ---------------------------------------------------------------------------
# TABLE REGEX
# ---------------------------------------------------------------------------

ROW = re.compile(
    r"\b(\d{1,2})\s+"
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b"
    r"(?:(?!\b\d{1,2}\s+"
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b).){0,160}?"
    r"\b(\d{1,3})\s+("
    + LEVEL_PATTERN
    + r")\b",
    re.I,
)

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


# ---------------------------------------------------------------------------
# HTML HELPERS
# ---------------------------------------------------------------------------

def flatten(html: str) -> str:
    """
    Convert HTML to normalized plain text.

    Used mainly for coefficient parsing and month/year detection.
    """

    if "</" in html:
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style"]):
            tag.decompose()

        html = soup.get_text(" ")

    return re.sub(r"\s+", " ", html)


def normalize(value) -> str:
    """
    Normalize an HTML attribute/string for searching.
    """

    if value is None:
        return ""

    if isinstance(value, (list, tuple)):
        value = " ".join(str(x) for x in value)

    return re.sub(r"\s+", " ", str(value)).strip().lower()


def collect_attributes(tag) -> str:
    """
    Collect potentially useful information from an HTML element.

    This is intentionally broad because Tides4Fishing can represent
    the fish indicator using an image, CSS class, background image,
    data attribute, etc.
    """

    values = []

    interesting_attributes = [
        "src",
        "class",
        "id",
        "style",
        "alt",
        "title",
        "aria-label",
        "data-level",
        "data-activity",
        "data-value",
        "data-rating",
        "data-score",
        "data-fish",
        "data-icon",
        "data-image",
        "data-src",
        "href",
    ]

    for attr in interesting_attributes:
        value = tag.get(attr)

        if value:
            values.append(normalize(value))

    return " ".join(values)


# ---------------------------------------------------------------------------
# MONTH/YEAR
# ---------------------------------------------------------------------------

def month_year_of_table(text: str, today: datetime.date):
    """
    Determine the month/year represented by the monthly tide table.
    """

    start = text.lower().find("tide table")

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
        (month.capitalize(), year)
        for month, year in hits
    )

    (month, year), _ = counts.most_common(1)[0]

    return int(year), MONTHS_EN.index(month) + 1


# ---------------------------------------------------------------------------
# COEFFICIENT PARSER
# ---------------------------------------------------------------------------

def parse_coefficients(text: str, today: datetime.date) -> dict:
    """
    Return:

        {
            date: "64 (sedang)",
            ...
        }

    from the COEFFICIENT column.
    """

    year, month = month_year_of_table(text, today)

    out = {}

    for match in ROW.finditer(text):
        day = int(match.group(1))
        value = match.group(2)
        raw_status = match.group(3).lower()

        try:
            date = datetime.date(
                year,
                month,
                day,
            )
        except ValueError:
            continue

        status = STATUS_MAP.get(
            raw_status,
            raw_status,
        )

        out.setdefault(
            date,
            f"{value} ({status})",
        )

    return out


# ---------------------------------------------------------------------------
# SOLUNAR ICON PARSER
# ---------------------------------------------------------------------------

def parse_activity_text(cell) -> str | None:
    """
    Look for a textual activity value inside a solunar cell.

    Examples:

        high
        high activity
        average
        low
        very high
    """

    hints = []

    # Visible text
    hints.append(
        normalize(cell.get_text(" ", strip=True))
    )

    # Cell attributes
    hints.append(
        collect_attributes(cell)
    )

    # Child element attributes
    for tag in cell.find_all(True):
        hints.append(
            collect_attributes(tag)
        )

    combined = " ".join(hints)

    match = LEVEL_ONLY.search(combined)

    if not match:
        return None

    raw = match.group(1).lower()

    return STATUS_MAP.get(raw)


def fish_number_from_attributes(attributes: str):
    """
    Try to determine the number of fish represented by an icon.

    This handles common patterns such as:

        fish0
        fish-0
        fish_0
        fish1
        fish-1
        fish_1
        fish2
        fish3

    It also handles things such as:

        activity3
        activity_3
        fish-active-3

    Returns:
        0..3
        None if no number can be determined.
    """

    text = normalize(attributes)

    # Explicit "grey/inactive/empty" indicators.
    if any(
        word in text
        for word in (
            "grey",
            "gray",
            "inactive",
            "disabled",
            "empty",
            "none",
            "off",
        )
    ):
        if "fish" in text or "activity" in text:
            return 0

    # Fish followed/preceded by a level number.
    patterns = [
        r"fish[\s_-]*([0-3])\b",
        r"\b([0-3])[\s_-]*fish\b",
        r"fish[a-z_-]*([0-3])\b",
        r"activity[\s_-]*([0-3])\b",
        r"level[\s_-]*([0-3])\b",
        r"rating[\s_-]*([0-3])\b",
        r"score[\s_-]*([0-3])\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return int(match.group(1))

    return None


def parse_fish_icon(cell):
    """
    Inspect the actual HTML inside a solunar activity cell.

    Returns:

        0 -> rendah
        1 -> sedang
        2 -> tinggi
        3 -> sangat tinggi

    or None if the icon cannot be decoded.

    We inspect IMG elements first, then other elements containing
    fish/activity-related attributes.
    """

    # ---------------------------------------------------------------
    # 1. Inspect images.
    # ---------------------------------------------------------------

    images = cell.find_all("img")

    for img in images:
        attributes = collect_attributes(img)

        if not attributes:
            continue

        if (
            "fish" not in attributes
            and "activity" not in attributes
            and "solunar" not in attributes
        ):
            continue

        number = fish_number_from_attributes(
            attributes
        )

        if number is not None:
            return number

    # ---------------------------------------------------------------
    # 2. Inspect all descendants.
    # ---------------------------------------------------------------

    for tag in cell.find_all(True):
        attributes = collect_attributes(tag)

        if not attributes:
            continue

        if (
            "fish" not in attributes
            and "activity" not in attributes
            and "solunar" not in attributes
        ):
            continue

        number = fish_number_from_attributes(
            attributes
        )

        if number is not None:
            return number

    # ---------------------------------------------------------------
    # 3. Check the cell itself.
    # ---------------------------------------------------------------

    attributes = collect_attributes(cell)

    number = fish_number_from_attributes(
        attributes
    )

    if number is not None:
        return number

    return None


# ---------------------------------------------------------------------------
# SOLUNAR TABLE PARSER
# ---------------------------------------------------------------------------

def parse_solunar(html: str, today: datetime.date):
    """
    Extract solunar activity from the monthly table.

    IMPORTANT:

    The parser only looks at the cell immediately following the
    coefficient cell.

    This prevents accidentally reading unrelated solunar values
    elsewhere on the page.

    Priority:

        1. Fish icon / HTML attributes
        2. Text / alt / title / aria-label
        3. Nothing -> caller uses astronomical fallback

    Returns:

        (
            {
                date: "rendah" / "sedang" / "tinggi" / "sangat tinggi"
            },
            sample_html
        )
    """

    out = {}
    sample = None

    if "</" not in html:
        return out, sample

    plain_text = flatten(html)

    year, month = month_year_of_table(
        plain_text,
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

        day_match = DAYROW.match(row_text)

        if not day_match:
            continue

        day_number = int(
            day_match.group(1)
        )

        cells = tr.find_all(
            ["td", "th"]
        )

        if not cells:
            continue

        # -----------------------------------------------------------
        # Find the COEFFICIENT cell.
        # -----------------------------------------------------------

        coefficient_index = None

        for i, cell in enumerate(cells):

            cell_text = " ".join(
                cell.get_text(" ").split()
            )

            if COEF_CELL.match(cell_text):
                coefficient_index = i
                break

        if coefficient_index is None:
            continue

        # The solunar activity cell should immediately follow
        # the coefficient cell.
        solunar_index = coefficient_index + 1

        if solunar_index >= len(cells):
            continue

        cell = cells[solunar_index]

        if sample is None:
            sample = str(tr)[:5000]

        # -----------------------------------------------------------
        # First attempt: inspect fish icon markup.
        # -----------------------------------------------------------

        fish_number = parse_fish_icon(cell)

        if fish_number is not None:

            level = LEVELS_ID[
                max(
                    0,
                    min(
                        3,
                        fish_number,
                    ),
                )
            ]

        else:

            # -------------------------------------------------------
            # Second attempt: textual information.
            # -------------------------------------------------------

            level = parse_activity_text(
                cell
            )

        if level is None:
            continue

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

        # Useful diagnostics while GitHub Actions runs.
        print(
            f"[solunar] "
            f"{date.isoformat()} -> {level}"
            + (
                f" (fish={fish_number})"
                if fish_number is not None
                else " (text)"
            )
        )

    return out, sample


# ---------------------------------------------------------------------------
# HTTP FETCH
# ---------------------------------------------------------------------------

def fetch_page(sample_file=None):
    """
    Download Tides4Fishing page.

    If --sample is supplied, use that local HTML file instead.
    """

    if sample_file:

        print(
            f"[scrape] menggunakan sample: {sample_file}"
        )

        with open(
            sample_file,
            encoding="utf-8",
        ) as file:
            return file.read()

    try:

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/124.0.0.0 "
                "Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8"
            ),
        }

        response = requests.get(
            URL,
            timeout=30,
            headers=headers,
        )

        print(
            f"[scrape] HTTP "
            f"{response.status_code}, "
            f"{len(response.text)} karakter"
        )

        if response.status_code != 200:

            print(
                "[scrape] respons awal:",
                response.text[:500]
                .replace("\n", " "),
            )

            return None

        return response.text

    except Exception:

        print("[scrape] ERROR:")
        traceback.print_exc()

        return None


# ---------------------------------------------------------------------------
# ASTRONOMICAL FALLBACK
# ---------------------------------------------------------------------------

def compute_days(
    today: datetime.date,
    n: int = 14,
):
    """
    Calculate moon/sun events for the next n days.

    This is ONLY used for:
        - major/minor period times
        - fallback solunar rating if the website cannot be parsed

    Coordinates:
        Palihan, Kulon Progo
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
            + datetime.timedelta(days=i)
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

        def event(
            function,
            body,
        ):
            try:
                event_time = function(body)

            except (
                ephem.NeverUpError,
                ephem.AlwaysUpError,
            ):
                return None

            dt = (
                ephem.Date(event_time)
                .datetime()
                .replace(tzinfo=UTC)
                .astimezone(TZ)
            )

            if start <= dt < end:
                return dt

            return None

        moon = ephem.Moon()
        sun = ephem.Sun()

        # Noon reference for moon-phase distance.
        reference = ephem.Date(
            float(observer.date) + 0.5
        )

        distance = min(
            abs(
                float(reference)
                - float(function(reference))
            )
            for function in (
                ephem.previous_new_moon,
                ephem.next_new_moon,
                ephem.previous_full_moon,
                ephem.next_full_moon,
            )
        )

        days.append(
            {
                "date": date,
                "dist": distance,

                "transit": event(
                    observer.next_transit,
                    moon,
                ),

                "anti": event(
                    observer.next_antitransit,
                    moon,
                ),

                "rise": event(
                    observer.next_rising,
                    moon,
                ),

                "set": event(
                    observer.next_setting,
                    moon,
                ),

                "sunrise": event(
                    observer.next_rising,
                    sun,
                ),

                "sunset": event(
                    observer.next_setting,
                    sun,
                ),
            }
        )

    return days


def estimate_solunar(day: dict) -> int:
    """
    Approximate solunar rating.

    This is NOT Tides4Fishing's calculation.

    It is only used if the website's solunar value
    cannot be extracted.

    Returns:

        0 -> rendah
        1 -> sedang
        2 -> tinggi
        3 -> sangat tinggi
    """

    distance = day["dist"]

    if distance <= 2:
        base = 2

    elif distance <= 5.5:
        b
