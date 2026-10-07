"""
Solunar RSS feed for Palihan, Yogyakarta.

Source:
https://tides4fishing.com/id/yogyakarta/palihan

Solunar activity is read directly from the fish icons.

The detailed solunar periods are read from the Tides4Fishing
"MAJOR PERIODS" and "MINOR PERIODS" blocks.
"""

import argparse
import datetime
import re
import traceback
from collections import Counter
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

URL = "https://tides4fishing.com/id/yogyakarta/palihan"

TZ = ZoneInfo("Asia/Jakarta")
UTC = datetime.timezone.utc

H1 = datetime.timedelta(hours=1)
M30 = datetime.timedelta(minutes=30)

DAYS_TO_GENERATE = 14


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


LEVELS_ID = [
    "rendah",
    "sedang",
    "tinggi",
    "sangat tinggi",
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

            match = re.match(
                r"^(\d{1,3})\s+(.+)$",
                cell_text,
                re.I,
            )

            if not match:
                continue

            coefficient = match.group(1)
            status_raw = match.group(2).lower()

            status_match = LEVEL_ONLY.search(
                status_raw
            )

            if not status_match:
                continue

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

    Active:
        icon-ic_pez_leyenda

    Grey/inactive:
        icon-ic_pez_leyenda2

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
    Extract daily SOLUNAR ACTIVITY from fish icons.
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

        activity_cells = tr.find_all(
            "td",
            class_="tabla_mareas_actividad",
        )

        if not activity_cells:
            continue

        cell = activity_cells[0]

        if sample is None:
            sample = str(tr)[:5000]

        active_fish = len(
            cell.find_all(
                "span",
                class_="icon-ic_pez_leyenda",
            )
        )

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
# DETAILED SOLUNAR PERIOD PARSER
# ============================================================

def activity_level_from_text(text):
    """
    Convert Tides4Fishing activity text
    into our Indonesian level.
    """

    match = LEVEL_ONLY.search(
        text or ""
    )

    if not match:
        return None

    return STATUS_MAP.get(
        match.group(1).lower()
    )


def level_number(level):
    """
    Convert activity level to numeric score.
    """

    return {
        "rendah": 0,
        "sedang": 1,
        "tinggi": 2,
        "sangat tinggi": 3,
    }.get(
        level,
        0,
    )


def parse_clock(value):
    """
    Convert 7:42 / 20:04 into minutes after midnight.
    """

    match = re.match(
        r"^\s*(\d{1,2}):(\d{2})\s*$",
        value or "",
    )

    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))

    if hour > 23 or minute > 59:
        return None

    return (
        hour * 60
        + minute
    )


def format_minutes(minutes):
    """
    Format minutes after midnight as HH:MM.
    """

    minutes = minutes % 1440

    hour = minutes // 60
    minute = minutes % 60

    return (
        f"{hour:02d}:"
        f"{minute:02d}"
    )


def parse_period_time_range(period):
    """
    Extract 'from HH:MM h to HH:MM h'.
    """

    text = " ".join(
        period.get_text(" ").split()
    )

    match = re.search(
        r"from\s+"
        r"(\d{1,2}:\d{2})"
        r".*?"
        r"to\s+"
        r"(\d{1,2}:\d{2})",
        text,
        re.I,
    )

    if not match:
        return None, None

    start = parse_clock(
        match.group(1)
    )

    end = parse_clock(
        match.group(2)
    )

    return start, end


def parse_detailed_periods(
    html: str,
):
    """
    Parse the MAJOR PERIODS and MINOR PERIODS
    directly from Tides4Fishing.

    Returns a list such as:

        {
            "type": "major",
            "level": "sangat tinggi",
            "start": 462,
            "end": 582,
            "name": "Lunar transit",
            "peak": False,
        }
    """

    result = []

    if not html:
        return result

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # --------------------------------------------------------
    # Find the main solunar periods container
    # --------------------------------------------------------

    intro = soup.find(
        id="salida_puesta_luna_periodos_intro"
    )

    if not intro:
        print(
            "[periods] Main solunar container not found."
        )
        return result

    container = intro.parent

    # --------------------------------------------------------
    # Find MAJOR / MINOR sections
    # --------------------------------------------------------

    sections = container.find_all(
        "div",
        class_="salida_puesta_luna_periodo",
        recursive=False,
    )

    # Sometimes the structure has an additional wrapper,
    # so use a broader fallback if necessary.
    if not sections:

        sections = container.find_all(
            "div",
            class_=lambda c: (
                c
                and "salida_puesta_luna_periodo" in c
                and (
                    "mayor" in c
                    or "menor" in c
                )
            ),
        )

    for section in sections:

        classes = section.get(
            "class",
            [],
        )

        if (
            "salida_puesta_luna_periodo_mayor"
            in classes
        ):
            period_type = "major"

        elif (
            "salida_puesta_luna_periodo_menor"
            in classes
        ):
            period_type = "minor"

        else:
            continue

        # ----------------------------------------------------
        # Individual period blocks
        # ----------------------------------------------------

        period_blocks = section.find_all(
            "div",
            class_="salida_puesta_luna_periodo_datos",
            recursive=False,
        )

        if not period_blocks:

            period_blocks = section.find_all(
                "div",
                class_=lambda c: (
                    c
                    and
                    "salida_puesta_luna_periodo_datos"
                    in c
                    and
                    "circulo"
                    not in c
                    and
                    "hora" not in c
                    and
                    "texto" not in c
                    and
                    "actividad" not in c
                ),
            )

        for period in period_blocks:

            text = " ".join(
                period.get_text(" ").split()
            )

            level = activity_level_from_text(
                text
            )

            if not level:
                continue

            start, end = parse_period_time_range(
                period
            )

            if start is None or end is None:
                continue

            # ------------------------------------------------
            # Period name
            # ------------------------------------------------

            name_node = period.find(
                class_=(
                    "salida_puesta_luna_periodo_datos_texto1"
                )
            )

            if name_node:

                name = " ".join(
                    name_node.get_text(" ").split()
                )

            else:

                name = ""

            # ------------------------------------------------
            # Detect special/peak/green period
            # ------------------------------------------------

            peak = False

            all_classes = []

            for element in period.find_all(
                True
            ):

                all_classes.extend(
                    element.get(
                        "class",
                        [],
                    )
                )

            class_text = " ".join(
                all_classes
            ).lower()

            if (
                "verde" in class_text
                or "green" in class_text
            ):
                peak = True

            # Also inspect style attributes.
            for element in period.find_all(
                True
            ):

                style = (
                    element.get(
                        "style",
                        "",
                    )
                    or ""
                ).lower()

                if (
                    "#3ebc47" in style
                    or "#00" in style
                    and "green" in style
                ):
                    peak = True

            result.append(
                {
                    "type": period_type,
                    "level": level,
                    "level_num": level_number(
                        level
                    ),
                    "start": start,
                    "end": end,
                    "name": name,
                    "peak": peak,
                }
            )

    print(
        f"[periods] Found "
        f"{len(result)} detailed periods."
    )

    for item in result:

        peak_text = (
            " PEAK"
            if item["peak"]
            else ""
        )

        print(
            "[periods] "
            f"{item['type']} | "
            f"{item['level']} | "
            f"{format_minutes(item['start'])}-"
            f"{format_minutes(item['end'])} | "
            f"{item['name']}"
            f"{peak_text}"
        )

    return result


# ============================================================
# BEST PERIOD SELECTION
# ============================================================

def select_best_periods(
    periods,
):
    """
    Select all periods with the highest activity.

    One period receives ⭐.

    Priority:
        1. Explicit peak/green period
        2. Otherwise first highest period chronologically
    """

    if not periods:
        return [], None

    highest = max(
        p["level_num"]
        for p in periods
    )

    highest_periods = [
        p
        for p in periods
        if p["level_num"] == highest
    ]

    highest_periods.sort(
        key=lambda p: p["start"]
    )

    # Explicit peak gets priority.
    peak_periods = [
        p
        for p in highest_periods
        if p["peak"]
    ]

    if peak_periods:

        best = peak_periods[0]

    else:

        best = highest_periods[0]

    return (
        highest_periods,
        best,
    )


def period_text(period):
    """
    Convert a period to:
        07:42–09:42
    """

    return (
        f"{format_minutes(period['start'])}"
        f"–"
        f"{format_minutes(period['end'])}"
    )


# ============================================================
# DAILY STATUS
# ============================================================

def fishing_status(level):
    """
    Convert fish activity level into the compact
    RSS title status.

    sangat tinggi -> SANGAT BAGUS
    tinggi        -> BAGUS
    sedang        -> SEDANG
    rendah        -> KURANG BAGUS
    """

    mapping = {
        "sangat tinggi": (
            "🟢",
            "SANGAT BAGUS",
        ),

        "tinggi": (
            "🟢",
            "BAGUS",
        ),

        "sedang": (
            "🟡",
            "SEDANG",
        ),

        "rendah": (
            "🔴",
            "KURANG BAGUS",
        ),
    }

    return mapping.get(
        level,
        ("🟡", "SEDANG"),
    )


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
# ASTRONOMICAL CALCULATION
# ============================================================

def compute_days(
    today: datetime.date,
    n: int = DAYS_TO_GENERATE,
):
    """
    Calculate moon/sun events.
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
        f"{_hm(t - delta)}–"
        f"{_hm(t + delta)}"
    )


# ============================================================
# FALLBACK PERIODS
# ============================================================

def astronomical_periods(day):
    """
    Create Major + Minor periods from ephem.

    Used when detailed Tides4Fishing periods
    are not available.
    """

    periods = []

    if day["transit"]:

        periods.append(
            {
                "type": "major",
                "level": None,
                "level_num": 0,
                "start": (
                    day["transit"]
                    - H1
                ),
                "end": (
                    day["transit"]
                    + H1
                ),
                "name": "Lunar transit",
                "peak": False,
            }
        )

    if day["anti"]:

        periods.append(
            {
                "type": "major",
                "level": None,
                "level_num": 0,
                "start": (
                    day["anti"]
                    - H1
                ),
                "end": (
                    day["anti"]
                    + H1
                ),
                "name": "Opposing lunar transit",
                "peak": False,
            }
        )

    if day["rise"]:

        periods.append(
            {
                "type": "minor",
                "level": None,
                "level_num": 0,
                "start": (
                    day["rise"]
                    - M30
                ),
                "end": (
                    day["rise"]
                    + M30
                ),
                "name": "Moonrise",
                "peak": False,
            }
        )

    if day["set"]:

        periods.append(
            {
                "type": "minor",
                "level": None,
                "level_num": 0,
                "start": (
                    day["set"]
                    - M30
                ),
                "end": (
                    day["set"]
                    + M30
                ),
                "name": "Moonset",
                "peak": False,
            }
        )

    # Convert datetime into minutes.
    converted = []

    for p in periods:

        start_dt = p["start"]
        end_dt = p["end"]

        start = (
            start_dt.hour * 60
            + start_dt.minute
        )

        end = (
            end_dt.hour * 60
            + end_dt.minute
        )

        converted.append(
            {
                **p,
                "start": start,
                "end": end,
            }
        )

    return converted


# ============================================================
# RSS ENTRY
# ============================================================

def build_entry(
    i,
    day,
    coefficient,
    solunar,
    from_site,
    detailed_periods=None,
):
    """
    Build RSS title + description.
    """

    date = day["date"]

    # --------------------------------------------------------
    # Label
    # --------------------------------------------------------

    if i == 0:

        label = (
            f"{date.day:02d} "
            f"{BULAN_INDO[date.month]}"
        )

    else:

        label = (
            f"{date.day:02d} "
            f"{BULAN_INDO[date.month]}"
        )

    # --------------------------------------------------------
    # Daily status
    # --------------------------------------------------------

    emoji, status = fishing_status(
        solunar
    )

    # --------------------------------------------------------
    # Detailed periods
    # --------------------------------------------------------

    periods = (
        detailed_periods
        if detailed_periods
        else []
    )

    # --------------------------------------------------------
    # If no detailed periods, create
    # astronomical fallback.
    # --------------------------------------------------------

    if not periods:

        periods = astronomical_periods(
            day
        )

        # Give fallback periods an equal
        # estimated activity level based
        # on the daily activity.
        level_num = level_number(
            solunar
        )

        for p in periods:
            p["level"] = solunar
            p["level_num"] = level_num

    # --------------------------------------------------------
    # Select highest periods
    # --------------------------------------------------------

    best_periods, starred = (
        select_best_periods(
            periods
        )
    )

    # --------------------------------------------------------
    # Title periods
    # --------------------------------------------------------

    title_periods = []

    for p in best_periods:

        text = period_text(
            p
        )

        if (
            starred is p
        ):
            text = "⭐ " + text

        title_periods.append(
            text
        )

    period_text_title = (
        ", ".join(title_periods)
        if title_periods
        else "-"
    )

    # --------------------------------------------------------
    # Final RSS title
    # --------------------------------------------------------

    title = (
        f"{emoji} {label} | "
        f"{status} | "
        f"{period_text_title}"
    )

    # --------------------------------------------------------
    # Description
    # --------------------------------------------------------

    if from_site:

        solunar_note = (
            "Data aktivitas ikan langsung "
            "dari Tides4Fishing."
        )

    else:

        solunar_note = (
            "Aktivitas ikan adalah perkiraan "
            "lokal karena data situs tidak "
            "tersedia untuk tanggal ini."
        )

    # --------------------------------------------------------
    # Detailed period description
    # --------------------------------------------------------

    major_lines = []
    minor_lines = []

    for p in sorted(
        periods,
        key=lambda x: x["start"],
    ):

        line = (
            f"{period_text(p)}"
        )

        if p.get("level"):
            line += (
                f" — "
                f"{p['level'].upper()}"
            )

        if p.get("name"):
            line += (
                f" — {p['name']}"
            )

        if p.get("peak"):
            line += " ⭐ PEAK"

        if p["type"] == "major":

            major_lines.append(
                line
            )

        else:

            minor_lines.append(
                line
            )

    major_text = (
        "<br>".join(
            major_lines
        )
        if major_lines
        else "-"
    )

    minor_text = (
        "<br>".join(
            minor_lines
        )
        if minor_lines
        else "-"
    )

    # --------------------------------------------------------
    # Old astronomical windows
    # --------------------------------------------------------

    major_1 = _win(
        day["transit"],
        H1,
    )

    major_2 = _win(
        day["anti"],
        H1,
    )

    minor_1 = _win(
        day["rise"],
        M30,
    )

    minor_2 = _win(
        day["set"],
        M30,
    )

    description = (
        "<h3>🎣 Aktivitas Ikan</h3>"
        f"<b>{solunar.upper()}</b>"
        "<br>"
        f"<i>{solunar_note}</i>"

        "<br><br>"

        "<h3>⭐ Waktu Terbaik</h3>"
        f"{period_text_title}"

        "<br><br>"

        "<h3>🌙 Major Periods</h3>"
        f"{major_text}"

        "<br><br>"

        "<h3>🌙 Minor Periods</h3>"
        f"{minor_text}"

        "<br><br>"

        "<h3>☀️ Matahari</h3>"
        f"Terbit: {_hm(day['sunrise'])}"
        "<br>"
        f"Terbenam: {_hm(day['sunset'])}"

        "<br><br>"

        "<h3>🌙 Perhitungan Astronomi</h3>"
        f"Major 1: {major_1}"
        "<br>"
        f"Major 2: {major_2}"
        "<br>"
        f"Moonrise: {minor_1}"
        "<br>"
        f"Moonset: {minor_2}"

        "<br><br>"

        "<h3>🌊 Koefisien Pasang Surut</h3>"
        f"{coefficient or '-'}"

        "<br><br>"

        "<small>"
        "Waktu solunar di atas bukan waktu "
        "pasang atau surut."
        "</small>"
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
    detailed_periods,
    now_time,
):
    from feedgen.feed import FeedGenerator

    feed = FeedGenerator()

    feed.title(
        "🎣 Waktu Mancing Palihan"
    )

    feed.link(
        href=URL,
        rel="alternate",
    )

    feed.description(
        "Informasi waktu terbaik untuk "
        "mancing di Palihan: aktivitas ikan, "
        "waktu solunar, matahari, bulan, "
        "dan koefisien pasang surut."
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

        # Detailed periods are currently
        # available directly from the page
        # for today's page.
        if i == 0:

            periods = (
                detailed_periods
                if detailed_periods
                else []
            )

        else:

            periods = []

        title, description = (
            build_entry(
                i,
                day,
                coefficients.get(date),
                solunar,
                from_site,
                periods,
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
    detailed_periods = []

    if raw:

        # ----------------------------------------------------
        # Coefficients
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
        # Daily fish activity
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

        # ----------------------------------------------------
        # Detailed Major + Minor periods
        # ----------------------------------------------------

        detailed_periods = (
            parse_detailed_periods(
                raw
            )
        )

        if not detailed_periods:

            print(
                "[periods] WARNING: "
                "No detailed periods found."
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
        DAYS_TO_GENERATE,
    )

    # --------------------------------------------------------
    # Generate RSS
    # --------------------------------------------------------

    write_feed(
        "palihan.xml",
        days,
        coefficients,
        site_solunar,
        detailed_periods,
        now_time,
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
