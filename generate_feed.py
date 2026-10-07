"""
Solunar Palihan - RSS generator.

Setiap tanggal mengambil data langsung dari Tides4Fishing.
Tidak menggunakan ephem untuk membuat / memperkirakan MAJOR dan MINOR.

Output:
    palihan.xml

Pakai:
    python generate_feed.py
"""

import argparse
import datetime
import re
import traceback
from collections import Counter
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


URL = "https://tides4fishing.com/id/yogyakarta/palihan"
TZ = ZoneInfo("Asia/Jakarta")

HARI_INDO = [
    "Sen", "Sel", "Rab", "Kam",
    "Jum", "Sab", "Min"
]

BULAN_INDO = [
    "",
    "Jan", "Feb", "Mar", "Apr",
    "Mei", "Jun", "Jul", "Agt",
    "Sep", "Okt", "Nov", "Des"
]

MONTHS_EN = [
    "January", "February", "March",
    "April", "May", "June",
    "July", "August", "September",
    "October", "November", "December"
]

LEVELS_ID = [
    "rendah",
    "sedang",
    "tinggi",
    "sangat tinggi"
]

STATUS_MAP = {
    "very high": "sangat tinggi",
    "high": "tinggi",
    "average": "sedang",
    "low": "rendah",

    "muy alta": "sangat tinggi",
    "alta": "tinggi",
    "media": "sedang",
    "baja": "rendah",

    "sangat tinggi": "sangat tinggi",
    "tinggi": "tinggi",
    "sedang": "sedang",
    "rendah": "rendah",
}

LEVEL_NUMBER = {
    "rendah": 0,
    "sedang": 1,
    "tinggi": 2,
    "sangat tinggi": 3,
}

LEVEL = (
    r"very high|muy alta|sangat tinggi|"
    r"high|average|low|alta|media|baja|"
    r"tinggi|sedang|rendah"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
}


# ============================================================
# BASIC
# ============================================================

def flatten(html: str) -> str:
    if "</" in html:
        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        for t in soup(["script", "style"]):
            t.decompose()

        html = soup.get_text(" ")

    return re.sub(
        r"\s+",
        " ",
        html
    ).strip()


def clean_text(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        text or ""
    ).strip()


def month_year_of_table(
    text: str,
    today: datetime.date
):
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
        re.I
    )

    if not hits:
        return today.year, today.month

    (mon, yr), _ = Counter(
        (m.capitalize(), y)
        for m, y in hits
    ).most_common(1)[0]

    return (
        int(yr),
        MONTHS_EN.index(mon) + 1
    )


# ============================================================
# MONTHLY COEFFICIENT
# ============================================================

ROW = re.compile(
    r"\b(\d{1,2})\s+"
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b"
    r"(?:(?!\b\d{1,2}\s+"
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b).){0,160}?"
    r"\b(\d{1,3})\s+("
    + LEVEL +
    r")\b",
    re.I
)


def parse_coefficients(
    text: str,
    today: datetime.date
) -> dict:

    year, month = month_year_of_table(
        text,
        today
    )

    out = {}

    for m in ROW.finditer(text):

        day = int(m.group(1))
        val = m.group(2)
        raw = m.group(3).lower()

        try:
            d = datetime.date(
                year,
                month,
                day
            )
        except ValueError:
            continue

        out.setdefault(
            d,
            f"{val} ({STATUS_MAP.get(raw, raw)})"
        )

    return out


# ============================================================
# DAILY SOLUNAR ACTIVITY FROM MONTHLY TABLE
# ============================================================

DAYROW = re.compile(
    r"^(\d{1,2})\s+"
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b",
    re.I
)

COEF_CELL = re.compile(
    r"^\d{1,3}\s+(?:"
    + LEVEL +
    r")$",
    re.I
)

LEVEL_ONLY = re.compile(
    r"\b("
    + LEVEL +
    r")\b",
    re.I
)


def parse_solunar(
    html: str,
    today: datetime.date
):

    out = {}
    sample = None

    if "</" not in html:
        return out, sample

    year, month = month_year_of_table(
        flatten(html),
        today
    )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    for tr in soup.find_all("tr"):

        text = clean_text(
            tr.get_text(" ")
        )

        m = DAYROW.match(text)

        if not m:
            continue

        cells = tr.find_all(
            ["td", "th"]
        )

        idx = next(
            (
                i
                for i, c in enumerate(cells)
                if COEF_CELL.match(
                    clean_text(
                        c.get_text(" ")
                    )
                )
            ),
            None
        )

        if idx is None:
            continue

        if idx + 1 >= len(cells):
            continue

        if sample is None:
            sample = str(tr)[:1500]

        cell = cells[idx + 1]

        hints = [
            cell.get_text(" ")
        ]

        for tag in cell.find_all(True):
            for attr in (
                "alt",
                "title",
                "aria-label"
            ):
                hints.append(
                    str(tag.get(attr, ""))
                )

        for attr in (
            "title",
            "aria-label"
        ):
            hints.append(
                str(cell.get(attr, ""))
            )

        lm = LEVEL_ONLY.search(
            " ".join(hints)
        )

        if not lm:
            continue

        try:
            d = datetime.date(
                year,
                month,
                int(m.group(1))
            )
        except ValueError:
            continue

        out.setdefault(
            d,
            STATUS_MAP[
                lm.group(1).lower()
            ]
        )

    return out, sample


# ============================================================
# FETCH
# ============================================================

def fetch_url(url: str):
    try:

        resp = requests.get(
            url,
            timeout=30,
            headers=HEADERS
        )

        print(
            f"[scrape] "
            f"{resp.status_code} "
            f"{url} "
            f"({len(resp.text)} karakter)"
        )

        if resp.status_code != 200:
            return None

        return resp.text

    except Exception:

        print(
            f"[scrape] ERROR: {url}"
        )

        traceback.print_exc()

        return None


def fetch_page(sample_file=None):

    if sample_file:

        with open(
            sample_file,
            encoding="utf-8"
        ) as f:
            return f.read()

    return fetch_url(URL)


# ============================================================
# DATE URL DISCOVERY
# ============================================================

def find_date_url(
    html: str,
    target: datetime.date
):
    """
    Mencari link yang benar-benar menunjuk ke tanggal.

    Tidak menebak format URL.
    """

    iso = target.isoformat()

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # --------------------------------------------------------
    # 1. href yang mengandung tanggal
    # --------------------------------------------------------

    for tag in soup.find_all(
        href=True
    ):

        href = tag.get(
            "href",
            ""
        )

        if iso in href:
            return urljoin(
                URL,
                href
            )

    # --------------------------------------------------------
    # 2. onclick Day('YYYY-MM-DD')
    # --------------------------------------------------------

    for tag in soup.find_all(
        onclick=True
    ):

        onclick = tag.get(
            "onclick",
            ""
        )

        if iso in onclick:

            # Kalau onclick memanggil URL langsung.
            m = re.search(
                r"""['"]([^'"]*"""
                + re.escape(iso)
                + r"""[^'"]*)['"]""",
                onclick
            )

            if m:
                candidate = m.group(1)

                if candidate.startswith(
                    "http"
                ):
                    return candidate

                if candidate.startswith(
                    "/"
                ):
                    return urljoin(
                        URL,
                        candidate
                    )

    return None


# ============================================================
# TIME
# ============================================================

def normalize_hm(
    hour,
    minute
):
    return (
        f"{int(hour):02d}:"
        f"{int(minute):02d}"
    )


def parse_time_range(
    text: str
):
    """
    Membaca:

        from 16:45 h to 17:45 h
    """

    m = re.search(
        r"from\s+"
        r"(\d{1,2}):(\d{2})\s*h?"
        r"\s+to\s+"
        r"(\d{1,2}):(\d{2})\s*h?",
        text,
        re.I
    )

    if not m:
        return None

    return (
        normalize_hm(
            m.group(1),
            m.group(2)
        ),
        normalize_hm(
            m.group(3),
            m.group(4)
        )
    )


# ============================================================
# ACTIVITY
# ============================================================

def activity_level(
    text: str
):
    t = clean_text(
        text
    ).lower()

    if "very high activity" in t:
        return 3

    if "high activity" in t:
        return 2

    if "average activity" in t:
        return 1

    if "low activity" in t:
        return 0

    if "very high" in t:
        return 3

    if "high" in t:
        return 2

    if "average" in t:
        return 1

    if "low" in t:
        return 0

    return None


def activity_name(
    level
):
    return LEVELS_ID[level]


# ============================================================
# PERIOD NAME
# ============================================================

def period_name(
    text: str
):
    names = [
        "Opposing lunar transit",
        "Lunar transit",
        "Moonrise",
        "Moonset",
    ]

    for name in names:

        if re.search(
            re.escape(name),
            text,
            re.I
        ):
            return name

    # Indonesian / Spanish fallback.
    lower = text.lower()

    if "transit lunar opuesto" in lower:
        return "Opposing lunar transit"

    if "tránsito lunar opuesto" in lower:
        return "Opposing lunar transit"

    if "tránsito lunar" in lower:
        return "Lunar transit"

    if "salida de la luna" in lower:
        return "Moonrise"

    if "puesta de la luna" in lower:
        return "Moonset"

    if "bulan terbit" in lower:
        return "Moonrise"

    if "bulan terbenam" in lower:
        return "Moonset"

    return "Solunar"


# ============================================================
# MAJOR / MINOR
# ============================================================

def period_kind(
    node,
    name
):
    lower = name.lower()

    if "lunar transit" in lower:
        return "major"

    if "moonrise" in lower:
        return "minor"

    if "moonset" in lower:
        return "minor"

    current = node

    for _ in range(8):

        if current is None:
            break

        classes = " ".join(
            current.get(
                "class",
                []
            )
        ).lower()

        if (
            "mayor" in classes
            or "major" in classes
        ):
            return "major"

        if (
            "menor" in classes
            or "minor" in classes
        ):
            return "minor"

        current = current.parent

    return "minor"


# ============================================================
# EXPLICIT GREEN / PEAK
# ============================================================

def explicit_peak(
    node
):
    """
    Mencari tanda green / verde / peak
    pada periode atau parent-nya.
    """

    current = node

    for _ in range(10):

        if current is None:
            break

        classes = " ".join(
            current.get(
                "class",
                []
            )
        ).lower()

        if any(
            x in classes
            for x in (
                "green",
                "verde",
                "peak"
            )
        ):
            return True

        # Cari juga teks "peak".
        txt = clean_text(
            current.get_text(" ")
        ).lower()

        if (
            "peak period" in txt
            or "peak periods" in txt
        ):
            return True

        current = current.parent

    return False


# ============================================================
# DETAILED MAJOR / MINOR PARSER
# ============================================================

def parse_detailed_periods(
    html: str
):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    periods = []
    seen = set()

    nodes = soup.find_all(
        class_=re.compile(
            r"salida_puesta_luna_periodo_datos"
        )
    )

    for node in nodes:

        text = clean_text(
            node.get_text(
                " ",
                strip=True
            )
        )

        time_range = parse_time_range(
            text
        )

        if not time_range:
            continue

        start, end = time_range

        level = activity_level(
            text
        )

        if level is None:
            continue

        name = period_name(
            text
        )

        kind = period_kind(
            node,
            name
        )

        peak = explicit_peak(
            node
        )

        key = (
            start,
            end,
            name,
            kind,
            level
        )

        if key in seen:
            continue

        seen.add(key)

        periods.append({
            "start": start,
            "end": end,
            "level": level,
            "name": name,
            "kind": kind,
            "explicit_peak": peak,
            "solar_peak": False,
        })

    periods.sort(
        key=lambda p: time_minutes(
            p["start"]
        )
    )

    return periods


# ============================================================
# SUNRISE / SUNSET
# ============================================================

def find_time_after_label(
    soup,
    labels
):
    """
    Cari waktu dekat label sunrise/sunset.
    """

    text = clean_text(
        soup.get_text(
            " ",
            strip=True
        )
    )

    for label in labels:

        m = re.search(
            re.escape(label)
            + r".{0,250}?"
            r"(\d{1,2}:\d{2})"
            r"(?::\d{2})?",
            text,
            re.I
        )

        if m:
            return normalize_hm(
                *m.group(1).split(":")
            )

    return None


def parse_sun_times(
    html: str
):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    sunrise = find_time_after_label(
        soup,
        [
            "sunrise",
            "sun rise",
            "sunrise:",
            "matahari terbit",
        ]
    )

    sunset = find_time_after_label(
        soup,
        [
            "sunset",
            "sun set",
            "sunset:",
            "matahari terbenam",
        ]
    )

    return sunrise, sunset


# ============================================================
# TIME COMPARISON
# ============================================================

def time_minutes(
    hm: str
):
    h, m = map(
        int,
        hm.split(":")
    )

    return h * 60 + m


def time_inside_period(
    event,
    start,
    end
):
    e = time_minutes(event)
    s = time_minutes(start)
    x = time_minutes(end)

    if s <= x:
        return s <= e <= x

    # Cross midnight.
    return e >= s or e <= x


# ============================================================
# STAR / BEST PERIODS
# ============================================================

def choose_periods(
    periods,
    sunrise,
    sunset
):
    """
    HANYA periode level tertinggi yang ditampilkan.

    ⭐ prioritas:

    1. explicit peak dari Tides4Fishing
    2. sunrise/sunset jatuh di dalam periode

    Tidak ada prioritas MAJOR terhadap MINOR.
    """

    if not periods:
        return [], []

    # --------------------------------------------------------
    # Solar coincidence
    # --------------------------------------------------------

    for p in periods:

        p["solar_peak"] = False

        if sunrise and time_inside_period(
            sunrise,
            p["start"],
            p["end"]
        ):
            p["solar_peak"] = True

        if sunset and time_inside_period(
            sunset,
            p["start"],
            p["end"]
        ):
            p["solar_peak"] = True

    # --------------------------------------------------------
    # Highest activity.
    # --------------------------------------------------------

    highest = max(
        p["level"]
        for p in periods
    )

    selected = [
        p
        for p in periods
        if p["level"] == highest
    ]

    selected.sort(
        key=lambda p:
        time_minutes(
            p["start"]
        )
    )

    # --------------------------------------------------------
    # Explicit Tides4Fishing peak.
    # --------------------------------------------------------

    explicit = [
        p
        for p in selected
        if p["explicit_peak"]
    ]

    if explicit:

        return selected, [
            explicit[0]
        ]

    # --------------------------------------------------------
    # Sunrise/sunset coincidence.
    #
    # Hanya periode level tertinggi.
    # --------------------------------------------------------

    solar = [
        p
        for p in selected
        if p["solar_peak"]
    ]

    if solar:

        return selected, [
            solar[0]
        ]

    # Tidak ada alasan sah untuk memberi ⭐.
    return selected, []


# ============================================================
# DAILY DATA
# ============================================================

def parse_daily_page(
    html: str
):
    periods = parse_detailed_periods(
        html
    )

    if not periods:
        return None

    sunrise, sunset = parse_sun_times(
        html
    )

    selected, stars = choose_periods(
        periods,
        sunrise,
        sunset
    )

    return {
        "periods": periods,
        "selected": selected,
        "stars": stars,
        "sunrise": sunrise,
        "sunset": sunset,
    }


# ============================================================
# FETCH EXACT DATE
# ============================================================

def fetch_exact_date(
    date: datetime.date,
    base_html: str
):
    """
    Ambil halaman tanggal tertentu.

    Pertama coba cari URL tanggal dari halaman utama.

    Kalau Tides4Fishing menggunakan mekanisme Day()
    yang tidak memberikan href langsung, kita coba pola
    URL yang ditemukan dari HTML/script.

    Tidak menggunakan ephem.
    """

    iso = date.isoformat()

    # --------------------------------------------------------
    # Cari href dengan ISO.
    # --------------------------------------------------------

    soup = BeautifulSoup(
        base_html,
        "html.parser"
    )

    candidates = []

    for tag in soup.find_all(
        href=True
    ):

        href = tag.get(
            "href",
            ""
        )

        if iso in href:
            candidates.append(
                urljoin(
                    URL,
                    href
                )
            )

    # --------------------------------------------------------
    # Cari URL ISO di HTML/script.
    # --------------------------------------------------------

    if not candidates:

        matches = re.findall(
            r"""(?:https?:)?//[^"' ]*"""
            + re.escape(iso)
            + r"""[^"' ]*""",
            base_html
        )

        for m in matches:
            candidates.append(
                m
            )

    # --------------------------------------------------------
    # Coba kandidat.
    # --------------------------------------------------------

    for candidate in candidates:

        page = fetch_url(
            candidate
        )

        if not page:
            continue

        parsed = parse_daily_page(
            page
        )

        if parsed:

            print(
                f"[date] {date} -> "
                f"{candidate}"
            )

            return page, parsed

    return None, None


# ============================================================
# DATE URL FROM CALENDAR
# ============================================================

def extract_calendar_urls(
    html: str
):
    """
    Membuat mapping:
        YYYY-MM-DD -> URL

    dari href / onclick / script.
    """

    result = {}

    # --------------------------------------------------------
    # href
    # --------------------------------------------------------

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    for tag in soup.find_all(
        href=True
    ):

        href = tag.get(
            "href",
            ""
        )

        dates = re.findall(
            r"20\d\d-\d\d-\d\d",
            href
        )

        for date_str in dates:

            result.setdefault(
                date_str,
                urljoin(
                    URL,
                    href
                )
            )

    # --------------------------------------------------------
    # onclick
    # --------------------------------------------------------

    for tag in soup.find_all(
        onclick=True
    ):

        onclick = tag.get(
            "onclick",
            ""
        )

        dates = re.findall(
            r"20\d\d-\d\d-\d\d",
            onclick
        )

        for date_str in dates:

            # Cari string URL bila ada.
            urls = re.findall(
                r"""['"]([^'"]+)['"]""",
                onclick
            )

            for u in urls:

                if (
                    date_str in u
                    and (
                        u.startswith("/")
                        or u.startswith("http")
                    )
                ):

                    result.setdefault(
                        date_str,
                        urljoin(
                            URL,
                            u
                        )
                    )

    # --------------------------------------------------------
    # raw HTML
    # --------------------------------------------------------

    for date_str in re.findall(
        r"20\d\d-\d\d-\d\d",
        html
    ):

        result.setdefault(
            date_str,
            None
        )

    return result


# ============================================================
# GET DAILY PAGE
# ============================================================

def get_daily_data(
    date,
    base_html,
    calendar_urls
):
    iso = date.isoformat()

    # --------------------------------------------------------
    # URL sudah diketahui
    # --------------------------------------------------------

    url = calendar_urls.get(
        iso
    )

    if url:

        page = fetch_url(
            url
        )

        if page:

            parsed = parse_daily_page(
                page
            )

            if parsed:

                return parsed

    # --------------------------------------------------------
    # Cari langsung dari base HTML
    # --------------------------------------------------------

    page, parsed = fetch_exact_date(
        date,
        base_html
    )

    if parsed:
        return parsed

    return None


# ============================================================
# STATUS
# ============================================================

def status_emoji(
    status
):
    if status == "sangat tinggi":
        return "🟢 SANGAT BAGUS"

    if status == "tinggi":
        return "🟢 BAGUS"

    if status == "sedang":
        return "🟡 SEDANG"

    if status == "rendah":
        return "🔴 BURUK"

    return "🔴 BURUK"


# ============================================================
# TITLE
# ============================================================

def build_title(
    date,
    status,
    selected,
    stars
):
    star_set = {
        (
            p["start"],
            p["end"],
            p["name"]
        )
        for p in stars
    }

    parts = []

    for p in selected:

        key = (
            p["start"],
            p["end"],
            p["name"]
        )

        prefix = (
            "⭐ "
            if key in star_set
            else ""
        )

        parts.append(
            prefix
            + p["start"]
            + "–"
            + p["end"]
        )

    periods = ", ".join(
        parts
    )

    status_text = status_emoji(
        status
    )

    return (
        f"{status_text} | "
        f"{date.day:02d} "
        f"{BULAN_INDO[date.month]} | "
        f"{periods or '-'}"
    )


# ============================================================
# DESCRIPTION
# ============================================================

def build_description(
    date,
    status,
    data,
    coefficient
):
    selected = data["selected"]
    stars = data["stars"]

    star_set = {
        (
            p["start"],
            p["end"],
            p["name"]
        )
        for p in stars
    }

    rows = []

    for p in selected:

        key = (
            p["start"],
            p["end"],
            p["name"]
        )

        star = (
            "⭐ "
            if key in star_set
            else ""
        )

        rows.append(
            "<tr>"
            f"<td>{star}"
            f"{p['start']}–{p['end']}</td>"
            f"<td>{p['name']}</td>"
            f"<td>{activity_name(p['level'])}</td>"
            f"<td>{p['kind'].upper()}</td>"
            "</tr>"
        )

    table = (
        "<table border='1' "
        "cellpadding='4' "
        "cellspacing='0'>"
        "<tr>"
        "<th>Waktu</th>"
        "<th>Periode</th>"
        "<th>Aktivitas</th>"
        "<th>Jenis</th>"
        "</tr>"
        + "".join(rows)
        + "</table>"
    )

    return (
        f"<b>{HARI_INDO[date.weekday()]}, "
        f"{date.day:02d} "
        f"{BULAN_INDO[date.month]}</b><br><br>"

        f"<b>Status:</b> "
        f"{status_emoji(status)}<br>"

        f"<b>Koefisien:</b> "
        f"{coefficient or '-'}<br>"

        f"<b>Sunrise:</b> "
        f"{data.get('sunrise') or '-'}<br>"

        f"<b>Sunset:</b> "
        f"{data.get('sunset') or '-'}<br><br>"

        "<b>Aktivitas tertinggi:</b><br>"

        f"{table}<br>"

        "<small>"
        "Sumber: Tides4Fishing"
        "</small>"
    )


# ============================================================
# WRITE RSS
# ============================================================

def write_feed(
    path,
    entries,
    now_time
):
    from feedgen.feed import FeedGenerator

    fg = FeedGenerator()

    fg.title(
        "Aktivitas Ikan Palihan"
    )

    fg.link(
        href=URL,
        rel="alternate"
    )

    fg.description(
        "Aktivitas ikan Palihan "
        "berdasarkan data solunar "
        "Tides4Fishing."
    )

    fg.language("id")

    for i, item in enumerate(
        entries
    ):

        date = item["date"]

        title = build_title(
            date,
            item["status"],
            item["data"]["selected"],
            item["data"]["stars"]
        )

        desc = build_description(
            date,
            item["status"],
            item["data"],
            item["coefficient"]
        )

        fe = fg.add_entry()

        fe.id(
            f"palihan-{date.isoformat()}"
        )

        fe.title(
            title
        )

        fe.link(
            href=URL
        )

        fe.description(
            desc
        )

        fe.pubDate(
            now_time
            - datetime.timedelta(
                hours=i
            )
        )

    fg.rss_file(
        path,
        pretty=True
    )

    print(
        f"[feed] {path} ditulis"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--sample",
        help="file HTML tersimpan untuk pengujian"
    )

    ap.add_argument(
        "--days",
        type=int,
        default=14,
        help="jumlah hari, default 14"
    )

    args = ap.parse_args()

    now_time = datetime.datetime.now(
        TZ
    )

    today = now_time.date()

    # --------------------------------------------------------
    # Ambil halaman utama.
    # --------------------------------------------------------

    raw = fetch_page(
        args.sample
    )

    if not raw:

        print(
            "[ERROR] Tidak bisa mengambil "
            "halaman Tides4Fishing."
        )

        return

    # --------------------------------------------------------
    # Data bulanan.
    # --------------------------------------------------------

    flat = flatten(
        raw
    )

    coefs, site_sol = parse_solunar(
        raw,
        today
    ), None

    # Perbaiki parsing koefisien.
    coefficients = parse_coefficients(
        flat,
        today
    )

    monthly_solunar, sample = parse_solunar(
        raw,
        today
    )

    print(
        f"[scrape] koefisien: "
        f"{len(coefficients)} hari"
    )

    print(
        f"[scrape] solunar bulanan: "
        f"{len(monthly_solunar)} hari"
    )

    # --------------------------------------------------------
    # Mapping URL tanggal.
    # --------------------------------------------------------

    calendar_urls = extract_calendar_urls(
        raw
    )

    print(
        f"[calendar] tanggal ditemukan: "
        f"{len(calendar_urls)}"
    )

    # --------------------------------------------------------
    # Ambil setiap tanggal.
    # --------------------------------------------------------

    entries = []

    for i in range(
        args.days
    ):

        date = (
            today
            + datetime.timedelta(
                days=i
            )
        )

        print()
        print(
            f"[{i + 1}/{args.days}] "
            f"Mengambil {date}"
        )

        data = get_daily_data(
            date,
            raw,
            calendar_urls
        )

        if not data:

            print(
                f"[ERROR] Data detail "
                f"{date} tidak ditemukan."
            )

            # JANGAN memakai ephem.
            # Lebih baik tanggal tidak dimasukkan
            # daripada mengirim data palsu.
            continue

        # ----------------------------------------------------
        # Status harian.
        #
        # Prioritas:
        # 1. tabel bulanan Tides4Fishing
        # 2. kalau tidak ada, level tertinggi periode.
        # ----------------------------------------------------

        status = monthly_solunar.get(
            date
        )

        if status is None:

            highest = max(
                p["level"]
                for p in data["periods"]
            )

            status = LEVELS_ID[
                highest
            ]

        entries.append({
            "date": date,
            "status": status,
            "data": data,
            "coefficient": coefficients.get(
                date
            ),
        })

        print(
            f"    Status: "
            f"{status_emoji(status)}"
        )

        for p in data["selected"]:

            star = (
                " ⭐"
                if p in data["stars"]
                else ""
            )

            print(
                f"    "
                f"{p['start']}–"
                f"{p['end']} | "
                f"{p['name']} | "
                f"{activity_name(p['level'])}"
                f"{star}"
            )

    # --------------------------------------------------------
    # RSS
    # --------------------------------------------------------

    if not entries:

        print(
            "[ERROR] Tidak ada data tanggal "
            "yang berhasil diambil."
        )

        return

    write_feed(
        "palihan.xml",
        entries,
        now_time
    )


if __name__ == "__main__":
    main()
