"""
generate_feed.py
RSS Solunar Palihan - data MAJOR/MINOR dibaca langsung
dari halaman tanggal Tides4Fishing.

Install:
    pip install selenium beautifulsoup4 feedgen

Chrome yang terpasang akan dipakai oleh Selenium Manager.
"""

import argparse
import datetime as dt
import html
import re
import time
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


URL = "https://tides4fishing.com/id/yogyakarta/palihan"
TZ = ZoneInfo("Asia/Jakarta")

DEFAULT_DAYS = 14

HARI = [
    "Sen", "Sel", "Rab", "Kam",
    "Jum", "Sab", "Min"
]

BULAN = [
    "",
    "Jan", "Feb", "Mar", "Apr",
    "Mei", "Jun", "Jul", "Agt",
    "Sep", "Okt", "Nov", "Des"
]

LEVEL = {
    "low": 1,
    "average": 2,
    "high": 3,
    "very high": 4,
}

STATUS = {
    1: "🔴 BURUK",
    2: "🟡 SEDANG",
    3: "🟢 BAGUS",
    4: "🟢 SANGAT BAGUS",
}

ACTIVITY_TEXT = {
    1: "LOW ACTIVITY",
    2: "AVERAGE ACTIVITY",
    3: "HIGH ACTIVITY",
    4: "VERY HIGH ACTIVITY",
}


# ============================================================
# BASIC HELPERS
# ============================================================

def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def minutes(hm):
    h, m = map(int, hm.split(":"))
    return h * 60 + m


def normalize_time(h, m):
    return f"{int(h):02d}:{int(m):02d}"


def in_period(event_hm, start_hm, end_hm):
    """
    Mendukung periode yang melewati tengah malam.

    Contoh:
        22:20 -> 00:20

    Maka 23:30 dan 00:10 dianggap berada di dalam periode.
    """

    event = minutes(event_hm)
    start = minutes(start_hm)
    end = minutes(end_hm)

    if start <= end:
        return start <= event <= end

    return event >= start or event <= end


# ============================================================
# ACTIVITY
# ============================================================

def activity_level(text):
    """
    Membaca:
        VERY HIGH ACTIVITY
        HIGH ACTIVITY
        AVERAGE ACTIVITY
        LOW ACTIVITY
    """

    t = clean(text).lower()

    if "very high activity" in t:
        return 4

    if "high activity" in t:
        return 3

    if "average activity" in t:
        return 2

    if "low activity" in t:
        return 1

    # Fallback jika HTML memisahkan kata activity.
    if "very high" in t:
        return 4

    if "high" in t:
        return 3

    if "average" in t:
        return 2

    if "low" in t:
        return 1

    return None


def activity_text(level):
    return ACTIVITY_TEXT.get(level, "UNKNOWN")


# ============================================================
# TIME RANGE
# ============================================================

def parse_time_range(text):
    """
    Contoh:
        from 16:45 h to 17:45 h
    """

    m = re.search(
        r"from\s+"
        r"(\d{1,2}):(\d{2})\s*h?"
        r"\s+to\s+"
        r"(\d{1,2}):(\d{2})\s*h?",
        text,
        re.I,
    )

    if not m:
        return None

    return (
        normalize_time(m.group(1), m.group(2)),
        normalize_time(m.group(3), m.group(4)),
    )


# ============================================================
# SUNRISE / SUNSET
# ============================================================

def parse_sun_times(soup):
    """
    Membaca sunrise/sunset dari halaman Tides4Fishing.

    Tidak dihitung dengan ephem.
    """

    text = clean(soup.get_text(" ", strip=True))

    sunrise = None
    sunset = None

    # Beberapa pola yang mungkin muncul pada halaman.
    patterns = [
        (
            r"sunrise\s+"
            r"(\d{1,2}:\d{2})(?::\d{2})?"
            r".{0,250}?"
            r"sunset\s+"
            r"(\d{1,2}:\d{2})(?::\d{2})?"
        ),
        (
            r"sun\s+(?:rise|rising|rose)"
            r".{0,150}?"
            r"(\d{1,2}:\d{2})(?::\d{2})?"
            r".{0,300}?"
            r"sunset"
            r".{0,150}?"
            r"(\d{1,2}:\d{2})(?::\d{2})?"
        ),
    ]

    for pattern in patterns:
        m = re.search(
            pattern,
            text,
            re.I | re.S,
        )

        if m:
            sunrise = normalize_time(
                *m.group(1).split(":")
            )

            sunset = normalize_time(
                *m.group(2).split(":")
            )

            break

    return sunrise, sunset


# ============================================================
# PERIOD NAME
# ============================================================

def get_period_name(text):
    """
    Mengambil nama astronomical event.

    Contoh:
        Lunar transit
        Opposing lunar transit
        Moonrise
        Moonset
    """

    patterns = [
        "Opposing lunar transit",
        "Lunar transit",
        "Moonrise",
        "Moonset",
    ]

    for name in patterns:
        if re.search(
            re.escape(name),
            text,
            re.I,
        ):
            return name

    return "Solunar"


# ============================================================
# MAJOR / MINOR
# ============================================================

def get_period_kind(node, name):
    """
    Menentukan MAJOR atau MINOR berdasarkan nama event
    atau class HTML parent.
    """

    name_lower = name.lower()

    if "lunar transit" in name_lower:
        return "major"

    if "moonrise" in name_lower:
        return "minor"

    if "moonset" in name_lower:
        return "minor"

    current = node

    for _ in range(8):

        if current is None:
            break

        classes = " ".join(
            current.get("class", [])
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
# EXPLICIT PEAK
# ============================================================

def is_explicit_peak(node):
    """
    Tides4Fishing memiliki penanda khusus untuk peak/green
    pada periode tertentu.

    Kita cek node dan beberapa parent-nya.
    """

    current = node

    for _ in range(8):

        if current is None:
            break

        classes = " ".join(
            current.get("class", [])
        ).lower()

        if any(
            marker in classes
            for marker in (
                "green",
                "verde",
                "peak",
            )
        ):
            return True

        current = current.parent

    return False


# ============================================================
# PARSE DETAILED PERIODS
# ============================================================

def parse_detailed_periods(soup):
    """
    Membaca MAJOR/MINOR langsung dari HTML halaman tanggal aktif.

    Tidak membuat periode sendiri menggunakan ephem.
    """

    periods = []
    seen = set()

    nodes = soup.find_all(
        class_=re.compile(
            r"salida_puesta_luna_periodo_datos"
        )
    )

    for node in nodes:

        text = clean(
            node.get_text(
                " ",
                strip=True
            )
        )

        time_range = parse_time_range(text)

        if not time_range:
            continue

        start, end = time_range

        level = activity_level(text)

        if level is None:
            continue

        name = get_period_name(text)

        kind = get_period_kind(
            node,
            name
        )

        explicit_peak = is_explicit_peak(
            node
        )

        key = (
            start,
            end,
            name.lower(),
            kind,
            level,
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
            "explicit_peak": explicit_peak,
            "solar_peak": False,
        })

    return periods


# ============================================================
# OVERALL DAILY ACTIVITY
# ============================================================

def parse_overall_activity(soup):
    """
    Mengambil aktivitas harian jika tersedia.

    Kalau tidak ditemukan, level tertinggi dari MAJOR/MINOR
    dipakai sebagai fallback.
    """

    text = clean(
        soup.get_text(
            " ",
            strip=True
        )
    ).lower()

    patterns = [
        r"solunar activity\s*[:\-]?\s*"
        r"(very high|high|average|low)",

        r"fish activity forecast\s+is\s+"
        r"(very high|high|average|low)",
    ]

    for pattern in patterns:

        m = re.search(
            pattern,
            text,
            re.I
        )

        if m:
            return LEVEL[
                m.group(1).lower()
            ]

    return None


# ============================================================
# STAR SELECTION
# ============================================================

def mark_solar_peaks(
    periods,
    sunrise,
    sunset
):
    """
    Sebuah periode dianggap peak apabila sunrise/sunset
    jatuh di dalam periode tersebut.

    Ini mengikuti penjelasan Tides4Fishing:
    ketika solunar period bertepatan dengan sunrise/sunset,
    aktivitas diperkirakan lebih tinggi.
    """

    for period in periods:

        peak = False

        if sunrise:

            if in_period(
                sunrise,
                period["start"],
                period["end"]
            ):
                peak = True

        if sunset:

            if in_period(
                sunset,
                period["start"],
                period["end"]
            ):
                peak = True

        period["solar_peak"] = peak


def choose_best_periods(
    periods,
    sunrise,
    sunset
):
    """
    Aturan:

    1. Ambil semua periode dengan level tertinggi.
    2. Jangan otomatis mengutamakan MAJOR.
    3. ⭐ hanya jika ada explicit peak atau solar coincidence.
    4. Jika ada explicit peak, explicit peak menang.
    5. Jika tidak ada explicit peak, pilih periode yang
       benar-benar bertepatan dengan sunrise/sunset.
    """

    if not periods:
        return [], []

    # Tandai coincidence sunrise/sunset.
    mark_solar_peaks(
        periods,
        sunrise,
        sunset
    )

    highest_level = max(
        p["level"]
        for p in periods
    )

    highest = [
        p
        for p in periods
        if p["level"] == highest_level
    ]

    highest.sort(
        key=lambda p: minutes(
            p["start"]
        )
    )

    # --------------------------------------------------------
    # Explicit peak dari Tides4Fishing
    # --------------------------------------------------------

    explicit = [
        p
        for p in periods
        if p["explicit_peak"]
    ]

    if explicit:

        peak_level = max(
            p["level"]
            for p in explicit
        )

        stars = [
            p
            for p in explicit
            if p["level"] == peak_level
        ]

        return highest, stars

    # --------------------------------------------------------
    # Kalau tidak ada explicit marker:
    # gunakan sunrise/sunset coincidence.
    # --------------------------------------------------------

    solar = [
        p
        for p in periods
        if p["solar_peak"]
    ]

    if not solar:
        return highest, []

    solar_level = max(
        p["level"]
        for p in solar
    )

    candidates = [
        p
        for p in solar
        if p["level"] == solar_level
    ]

    # Normalnya hanya satu ⭐.
    #
    # Urutan:
    # - level tertinggi
    # - lalu periode yang paling dekat dengan sunrise/sunset
    # - lalu waktu mulai.
    #
    # Jangan memakai MAJOR sebagai prioritas otomatis.

    def solar_distance(period):

        distances = []

        if sunrise:

            distances.append(
                distance_to_period(
                    sunrise,
                    period
                )
            )

        if sunset:

            distances.append(
                distance_to_period(
                    sunset,
                    period
                )
            )

        return min(distances)

    candidates.sort(
        key=lambda p: (
            solar_distance(p),
            minutes(p["start"])
        )
    )

    return highest, [candidates[0]]


def distance_to_period(
    event_hm,
    period
):
    """
    0 jika event berada di dalam periode.
    Dipakai hanya untuk tie-breaking.
    """

    if in_period(
        event_hm,
        period["start"],
        period["end"]
    ):
        return 0

    event = minutes(event_hm)
    start = minutes(period["start"])
    end = minutes(period["end"])

    if start <= end:

        if event < start:
            return start - event

        return event - end

    # Cross midnight.
    if event > end and event < start:
        return min(
            event - end,
            start - event
        )

    return 0


# ============================================================
# COEFFICIENT
# ============================================================

def parse_coefficient(
    soup,
    target_date
):
    """
    Membaca koefisien dari tabel bulanan jika tersedia.
    """

    target_day = str(
        target_date.day
    )

    for tr in soup.find_all("tr"):

        row = clean(
            tr.get_text(
                " ",
                strip=True
            )
        )

        if not re.search(
            rf"\b{re.escape(target_day)}\b",
            row
        ):
            continue

        # Contoh umum:
        # 7 Wed 81 high
        m = re.search(
            r"\b(\d{1,3})\b\s+"
            r"(very high|high|average|low)\b",
            row,
            re.I
        )

        if m:
            return (
                f"{m.group(1)} "
                f"({m.group(2).lower()})"
            )

    # Fallback dari halaman tanggal.
    text = clean(
        soup.get_text(
            " ",
            strip=True
        )
    )

    m = re.search(
        r"tidal coefficient today is\s+"
        r"(\d{1,3})",
        text,
        re.I
    )

    if m:
        return m.group(1)

    return "-"


# ============================================================
# DATE LABEL
# ============================================================

def date_label(date):
    return (
        f"{HARI[date.weekday()]} "
        f"{date.day:02d} "
        f"{BULAN[date.month]}"
    )


# ============================================================
# RSS TITLE
# ============================================================

def build_title(
    date,
    status_level,
    selected,
    stars
):
    """
    Contoh:

    🟢 10 Okt | SANGAT BAGUS |
    ⭐ 16:45–17:45, 04:15–05:15,
    10:00–12:00, 22:20–00:20
    """

    status = STATUS.get(
        status_level,
        "🟡 SEDANG"
    )

    star_keys = {
        (
            p["start"],
            p["end"],
            p["name"]
        )
        for p in stars
    }

    parts = []

    for period in selected:

        key = (
            period["start"],
            period["end"],
            period["name"]
        )

        prefix = (
            "⭐ "
            if key in star_keys
            else ""
        )

        parts.append(
            prefix
            + period["start"]
            + "–"
            + period["end"]
        )

    periods = ", ".join(parts)

    # Emoji status hanya satu.
    emoji = status[:2]

    status_without_emoji = status[2:].strip()

    return (
        f"{emoji} "
        f"{date.day:02d} {BULAN[date.month]} | "
        f"{status_without_emoji} | "
        f"{periods or '-'}"
    )


# ============================================================
# RSS DESCRIPTION
# ============================================================

def build_description(
    date,
    data,
    coefficient
):
    selected = data["selected"]
    stars = data["stars"]

    star_keys = {
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
            "⭐"
            if key in star_keys
            else ""
        )

        rows.append(
            "<tr>"
            f"<td>{html.escape(star)}</td>"
            f"<td>{html.escape(p['start'])}"
            f"–{html.escape(p['end'])}</td>"
            f"<td>{html.escape(p['name'])}</td>"
            f"<td>{html.escape(activity_text(p['level']))}</td>"
            f"<td>{html.escape(p['kind'].upper())}</td>"
            "</tr>"
        )

    table = (
        "<table border='1' "
        "cellpadding='5' "
        "cellspacing='0'>"
        "<tr>"
        "<th></th>"
        "<th>Waktu</th>"
        "<th>Periode</th>"
        "<th>Aktivitas</th>"
        "<th>Jenis</th>"
        "</tr>"
        + "".join(rows)
        + "</table>"
    )

    status = STATUS.get(
        data["status_level"],
        "🟡 SEDANG"
    )

    return (
        f"<b>{html.escape(date_label(date))}</b><br>"
        f"<b>Status:</b> {html.escape(status)}<br>"
        f"<b>Koefisien pasang surut:</b> "
        f"{html.escape(coefficient)}<br>"
        f"<b>Sunrise:</b> "
        f"{html.escape(data['sunrise'] or '-')}<br>"
        f"<b>Sunset:</b> "
        f"{html.escape(data['sunset'] or '-')}<br>"
        "<br>"
        "<b>Periode aktivitas tertinggi:</b><br>"
        f"{table}<br>"
        "<small>"
        "Sumber: Tides4Fishing"
        "</small>"
    )


# ============================================================
# SELENIUM
# ============================================================

def make_driver():
    options = webdriver.ChromeOptions()

    options.add_argument(
        "--headless=new"
    )

    options.add_argument(
        "--disable-gpu"
    )

    options.add_argument(
        "--no-sandbox"
    )

    options.add_argument(
        "--disable-dev-shm-usage"
    )

    options.add_argument(
        "--window-size=1600,1200"
    )

    options.add_argument(
        "--lang=en-US"
    )

    options.add_argument(
        "--user-agent=Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )

    return webdriver.Chrome(
        options=options
    )


def wait_for_page(driver):
    WebDriverWait(
        driver,
        30
    ).until(
        lambda d:
        d.find_element(
            By.TAG_NAME,
            "body"
        )
    )


# ============================================================
# OPEN SPECIFIC DATE
# ============================================================

def open_date(
    driver,
    target_date
):
    """
    Tides4Fishing menggunakan:

        javascript:Day('YYYY-MM-DD');

    Jadi kita klik tombol kalender tersebut.

    Kita sengaja TIDAK menebak:
        ?date=
        ?day=
        /YYYY-MM-DD

    """

    iso = target_date.isoformat()

    element = None

    # --------------------------------------------------------
    # Cara pertama: CSS onclick
    # --------------------------------------------------------

    selectors = [
        f"[onclick*=\"{iso}\"]",
        f"[onclick*=\"'{iso}'\"]",
        f"[onclick*='\"{iso}\"']",
    ]

    for selector in selectors:

        try:

            elements = driver.find_elements(
                By.CSS_SELECTOR,
                selector
            )

            if elements:

                element = elements[0]
                break

        except Exception:
            pass

    # --------------------------------------------------------
    # Cara kedua: scan semua onclick
    # --------------------------------------------------------

    if element is None:

        elements = driver.find_elements(
            By.XPATH,
            "//*[@onclick]"
        )

        for el in elements:

            onclick = (
                el.get_attribute(
                    "onclick"
                )
                or ""
            )

            if iso in onclick:

                element = el
                break

    if element is None:

        raise RuntimeError(
            f"Tombol kalender untuk "
            f"{iso} tidak ditemukan."
        )

    # Scroll ke tombol.
    driver.execute_script(
        """
        arguments[0].scrollIntoView({
            block: 'center'
        });
        """,
        element
    )

    time.sleep(0.2)

    # Klik.
    try:

        element.click()

    except Exception:

        driver.execute_script(
            "arguments[0].click();",
            element
        )

    # Tunggu DOM berubah / selesai.
    WebDriverWait(
        driver,
        30
    ).until(
        lambda d:
        "SOLUNAR ACTIVITY"
        in clean(
            d.find_element(
                By.TAG_NAME,
                "body"
            ).text
        ).upper()
    )

    time.sleep(0.7)


# ============================================================
# SCRAPE ONE DATE
# ============================================================

def scrape_current_page(
    driver,
    date
):
    source = driver.page_source

    soup = BeautifulSoup(
        source,
        "html.parser"
    )

    periods = parse_detailed_periods(
        soup
    )

    if not periods:

        raise RuntimeError(
            f"{date.isoformat()}: "
            "MAJOR/MINOR tidak ditemukan."
        )

    sunrise, sunset = parse_sun_times(
        soup
    )

    selected, stars = choose_best_periods(
        periods,
        sunrise,
        sunset
    )

    overall = parse_overall_activity(
        soup
    )

    # Jika aktivitas harian tidak ada,
    # gunakan level tertinggi MAJOR/MINOR.
    if overall is None:

        overall = max(
            p["level"]
            for p in periods
        )

    coefficient = parse_coefficient(
        soup,
        date
    )

    return {
        "status_level": overall,
        "sunrise": sunrise,
        "sunset": sunset,
        "periods": periods,
        "selected": selected,
        "stars": stars,
        "coefficient": coefficient,
    }


# ============================================================
# SCRAPE N DAYS
# ============================================================

def scrape_days(
    start_date,
    number_of_days
):
    driver = make_driver()

    results = {}

    try:

        print()
        print(
            "Membuka Tides4Fishing..."
        )

        driver.get(URL)

        wait_for_page(
            driver
        )

        for index in range(
            number_of_days
        ):

            date = (
                start_date
                + dt.timedelta(days=index)
            )

            print(
                f"[{index + 1}/"
                f"{number_of_days}] "
                f"{date.isoformat()}"
            )

            if index > 0:

                open_date(
                    driver,
                    date
                )

            data = scrape_current_page(
                driver,
                date
            )

            results[date] = data

            print(
                f"    Status: "
                f"{STATUS[data['status_level']]}"
            )

            for period in data["selected"]:

                star = (
                    " ⭐"
                    if period in data["stars"]
                    else ""
                )

                print(
                    f"    "
                    f"{period['start']}"
                    f"-"
                    f"{period['end']} "
                    f"{period['name']} "
                    f"{activity_text(period['level'])}"
                    f"{star}"
                )

    finally:

        driver.quit()

    return results


# ============================================================
# WRITE RSS
# ============================================================

def write_feed(
    output,
    results
):
    feed = FeedGenerator()

    feed.title(
        "Aktivitas Ikan Palihan"
    )

    feed.link(
        href=URL,
        rel="alternate"
    )

    feed.description(
        "Aktivitas ikan dan waktu "
        "solunar Palihan berdasarkan "
        "Tides4Fishing."
    )

    feed.language("id")

    now = dt.datetime.now(TZ)

    for index, (
        date,
        data
    ) in enumerate(
        results.items()
    ):

        title = build_title(
            date,
            data["status_level"],
            data["selected"],
            data["stars"]
        )

        description = build_description(
            date,
            data,
            data["coefficient"]
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
            now - dt.timedelta(
                minutes=index
            )
        )

    feed.rss_file(
        output,
        pretty=True
    )

    print()
    print(
        f"RSS berhasil dibuat: "
        f"{output}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=(
            "Jumlah hari yang diambil. "
            "Default: 14"
        )
    )

    parser.add_argument(
        "--output",
        default="palihan.xml",
        help=(
            "Nama file RSS. "
            "Default: palihan.xml"
        )
    )

    args = parser.parse_args()

    now = dt.datetime.now(
        TZ
    )

    start_date = now.date()

    print(
        "========================================"
    )
    print(
        " RSS AKTIVITAS IKAN PALIHAN"
    )
    print(
        "========================================"
    )

    print(
        f"Mulai : {start_date}"
    )

    print(
        f"Hari  : {args.days}"
    )

    print(
        "Sumber: Tides4Fishing"
    )

    print(
        "Mode  : BACA DATA TIAP TANGGAL"
    )

    print(
        "========================================"
    )

    results = scrape_days(
        start_date,
        args.days
    )

    write_feed(
        args.output,
        results
    )


if __name__ == "__main__":
    main()
