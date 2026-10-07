import argparse
import datetime as dt
import re
import traceback
from collections import Counter
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

try:
    import ephem
except ImportError:
    ephem = None


URL = "https://tides4fishing.com/id/yogyakarta/palihan"
TZ = ZoneInfo("Asia/Jakarta")

H1 = dt.timedelta(hours=1)
M30 = dt.timedelta(minutes=30)

ID_WEEKDAYS = [
    "Senin", "Selasa", "Rabu", "Kamis",
    "Jumat", "Sabtu", "Minggu"
]

ID_MONTHS = [
    "Januari", "Februari", "Maret", "April",
    "Mei", "Juni", "Juli", "Agustus",
    "September", "Oktober", "November", "Desember"
]

LEVELS_ID = [
    "rendah",
    "sedang",
    "tinggi",
    "sangat tinggi"
]

STATUS_MAP = {
    "LOW": "rendah",
    "AVERAGE": "sedang",
    "MEDIUM": "sedang",
    "HIGH": "tinggi",
    "VERY HIGH": "sangat tinggi",
}


# ============================================================
# BASIC HELPERS
# ============================================================

def flatten(text):
    if not text:
        return ""

    soup = BeautifulSoup(str(text), "html.parser")
    return " ".join(soup.stripped_strings)


def month_year_of_table(soup):
    text = soup.get_text(" ", strip=True)

    month_map = {
        "JANUARY": 1,
        "FEBRUARY": 2,
        "MARCH": 3,
        "APRIL": 4,
        "MAY": 5,
        "JUNE": 6,
        "JULY": 7,
        "AUGUST": 8,
        "SEPTEMBER": 9,
        "OCTOBER": 10,
        "NOVEMBER": 11,
        "DECEMBER": 12,
    }

    for name, number in month_map.items():
        m = re.search(
            rf"\b{name}\s*,?\s*(20\d{{2}})\b",
            text,
            re.I
        )
        if m:
            return number, int(m.group(1))

        m = re.search(
            rf"\b{name}\s+(20\d{{2}})\b",
            text,
            re.I
        )
        if m:
            return number, int(m.group(1))

    return None, None


# ============================================================
# TIDE / FISH ACTIVITY
# ============================================================

def parse_coefficients(soup):
    result = {}

    month, year = month_year_of_table(soup)

    if not month or not year:
        return result

    rows = soup.find_all("tr")

    for row in rows:
        cells = row.find_all(["td", "th"])

        if not cells:
            continue

        text = flatten(row)

        m = re.search(
            r"\b([1-9]|[12]\d|3[01])\b.*?"
            r"\b(\d{1,3})\b\s*"
            r"(very high|high|average|medium|low)",
            text,
            re.I
        )

        if not m:
            continue

        day = int(m.group(1))
        coefficient = int(m.group(2))
        status = m.group(3).lower()

        result[day] = {
            "date": dt.date(year, month, day),
            "coefficient": coefficient,
            "status": status,
        }

    return result


def parse_fish_activity(row):
    """
    Tides4Fishing menggunakan ikon ikan:

      icon-ic_pez_leyenda   = aktif
      icon-ic_pez_leyenda2  = tidak aktif

    Jumlah ikan aktif:
      0 = rendah
      1 = sedang
      2 = tinggi
      3+ = sangat tinggi
    """

    classes = []

    for tag in row.find_all(True):
        cls = tag.get("class", [])

        if isinstance(cls, str):
            cls = [cls]

        classes.extend(cls)

    active = sum(
        1
        for c in classes
        if c == "icon-ic_pez_leyenda"
    )

    inactive = sum(
        1
        for c in classes
        if c == "icon-ic_pez_leyenda2"
    )

    total = active + inactive

    if total == 0:
        return None

    if active <= 0:
        level = "rendah"
    elif active == 1:
        level = "sedang"
    elif active == 2:
        level = "tinggi"
    else:
        level = "sangat tinggi"

    return {
        "active": active,
        "inactive": inactive,
        "total": total,
        "level": level,
    }


def parse_solunar(soup):
    """
    Ambil aktivitas ikan harian dari tabel Tides4Fishing.
    """

    result = {}

    for row in soup.find_all("tr"):
        text = flatten(row)

        if not re.search(
            r"\b(LOW|AVERAGE|MEDIUM|HIGH|VERY HIGH)\b",
            text,
            re.I
        ):
            continue

        m = re.search(
            r"^\s*(\d{1,2})\b",
            text
        )

        if not m:
            continue

        day = int(m.group(1))

        fish = parse_fish_activity(row)

        if fish:
            result[day] = fish

    return result


# ============================================================
# DETAILED SOLUNAR PERIODS
# ============================================================

def activity_level_from_text(text):
    text = text.upper()

    if "VERY HIGH" in text:
        return "sangat tinggi"

    if "HIGH" in text:
        return "tinggi"

    if "AVERAGE" in text or "MEDIUM" in text:
        return "sedang"

    if "LOW" in text:
        return "rendah"

    return None


def level_number(level):
    return {
        "rendah": 0,
        "sedang": 1,
        "tinggi": 2,
        "sangat tinggi": 3,
    }.get(level, 0)


def parse_clock(value):
    """
    7:42
    07:42
    7.42
    """

    if not value:
        return None

    value = value.strip().replace(".", ":")

    m = re.match(
        r"^(\d{1,2}):(\d{2})$",
        value
    )

    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2))

    if hour > 23 or minute > 59:
        return None

    return hour * 60 + minute


def format_minutes(minutes):
    minutes = minutes % (24 * 60)

    hour = minutes // 60
    minute = minutes % 60

    return f"{hour:02d}:{minute:02d}"


def parse_period_time_range(text):
    """
    Contoh:
        from 7:42 h to 9:42 h

    Menghasilkan:
        (462, 582)
    """

    m = re.search(
        r"from\s+(\d{1,2}:\d{2})\s*h?\s+"
        r"to\s+(\d{1,2}:\d{2})\s*h?",
        text,
        re.I
    )

    if not m:
        return None

    start = parse_clock(m.group(1))
    end = parse_clock(m.group(2))

    if start is None or end is None:
        return None

    return start, end


def parse_detailed_periods(soup):
    """
    Membaca:

        MAJOR PERIODS
        MINOR PERIODS

    dari halaman Tides4Fishing.

    Menghasilkan list seperti:

        {
            "type": "major",
            "level": "sangat tinggi",
            "level_num": 3,
            "start": 462,
            "end": 582,
            "name": "Lunar transit",
            "peak": False
        }
    """

    periods = []

    # --------------------------------------------------------
    # Cari blok periode secara langsung.
    # Ini sengaja tidak bergantung pada struktur parent tertentu
    # karena HTML Tides4Fishing mempunyai wrapper bertingkat.
    # --------------------------------------------------------

    blocks = soup.find_all(
        "div",
        class_=lambda c: (
            c
            and "salida_puesta_luna_periodo" in c
            and (
                "salida_puesta_luna_periodo_mayor" in c
                or "salida_puesta_luna_periodo_menor" in c
            )
        )
    )

    for block in blocks:

        classes = block.get("class", [])

        if "salida_puesta_luna_periodo_mayor" in classes:
            period_type = "major"
        elif "salida_puesta_luna_periodo_menor" in classes:
            period_type = "minor"
        else:
            continue

        # ----------------------------------------------------
        # Setiap blok biasanya memiliki div:
        #
        # salida_puesta_luna_periodo_datos
        # ----------------------------------------------------

        data_blocks = block.find_all(
            "div",
            class_=lambda c: (
                c and
                "salida_puesta_luna_periodo_datos" in c
            )
        )

        for data in data_blocks:

            text = flatten(data)

            time_range = parse_period_time_range(text)

            if not time_range:
                continue

            start, end = time_range

            level = activity_level_from_text(text)

            if not level:
                continue

            # ------------------------------------------------
            # Nama periode
            # ------------------------------------------------

            name = ""

            for candidate in [
                "Lunar transit",
                "Opposing lunar transit",
                "Moonrise",
                "Moonset",
            ]:
                if candidate.lower() in text.lower():
                    name = candidate
                    break

            if not name:
                # fallback: ambil teks setelah range
                clean = re.sub(
                    r"from\s+\d{1,2}:\d{2}\s*h?\s+"
                    r"to\s+\d{1,2}:\d{2}\s*h?",
                    "",
                    text,
                    flags=re.I
                )

                name = clean.strip()

            # ------------------------------------------------
            # Deteksi explicit green / peak jika ada di HTML.
            # ------------------------------------------------

            data_classes = data.get("class", [])

            if isinstance(data_classes, str):
                data_classes = [data_classes]

            full_class_text = " ".join(data_classes).lower()

            peak = (
                "green" in full_class_text
                or "verde" in full_class_text
                or "peak" in full_class_text
            )

            periods.append({
                "type": period_type,
                "level": level,
                "level_num": level_number(level),
                "start": start,
                "end": end,
                "name": name,
                "peak": peak,
            })

    # Hilangkan duplikat
    unique = []

    seen = set()

    for p in periods:
        key = (
            p["type"],
            p["start"],
            p["end"],
            p["name"],
            p["level"],
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(p)

    unique.sort(
        key=lambda p: (
            p["start"],
            p["end"]
        )
    )

    return unique


# ============================================================
# PEAK DETECTION
# ============================================================

def datetime_to_minutes(value):
    if value is None:
        return None

    if isinstance(value, dt.datetime):
        return value.hour * 60 + value.minute

    if isinstance(value, dt.time):
        return value.hour * 60 + value.minute

    return None


def time_inside_period(event_minute, start, end):
    """
    Cek apakah sunrise/sunset jatuh di dalam periode.

    Mendukung periode melewati tengah malam.

    Contoh:
        22:20 -> 00:20

    sunset 23:00 => True
    """

    if event_minute is None:
        return False

    if start <= end:
        return start <= event_minute <= end

    # Cross midnight
    return (
        event_minute >= start
        or event_minute <= end
    )


def period_is_solar_peak(period, day):
    """
    ⭐ ditentukan berdasarkan:

    1. Explicit green/peak class dari HTML
    ATAU
    2. Sunrise jatuh dalam periode
    ATAU
    3. Sunset jatuh dalam periode

    Tides4Fishing menjelaskan bahwa periode yang
    bertepatan dengan sunrise/sunset adalah peak period.
    """

    if period.get("peak"):
        return True

    sunrise = datetime_to_minutes(
        day.get("sunrise")
    )

    sunset = datetime_to_minutes(
        day.get("sunset")
    )

    if time_inside_period(
        sunrise,
        period["start"],
        period["end"]
    ):
        return True

    if time_inside_period(
        sunset,
        period["start"],
        period["end"]
    ):
        return True

    return False


def select_best_periods(periods, day):
    """
    Mengembalikan:

        displayed_periods
        starred_period

    ATURAN:

    - Tampilkan semua periode dengan aktivitas tertinggi.
    - ⭐ hanya berdasarkan peak/sunrise/sunset.
    - JANGAN pernah otomatis memilih periode pertama.
    """

    if not periods:
        return [], None

    # --------------------------------------------------------
    # Level tertinggi
    # --------------------------------------------------------

    highest_level = max(
        p["level_num"]
        for p in periods
    )

    highest_periods = [
        p for p in periods
        if p["level_num"] == highest_level
    ]

    # --------------------------------------------------------
    # Cari peak.
    #
    # Penting:
    # kita cari dari SEMUA periode, bukan hanya VERY HIGH.
    #
    # Jadi apabila Moonset adalah peak karena sunset,
    # Moonset bisa menjadi ⭐ walaupun nominalnya HIGH.
    # --------------------------------------------------------

    peak_periods = [
        p for p in periods
        if period_is_solar_peak(p, day)
    ]

    starred = None

    if peak_periods:

        # Kalau ada beberapa peak:
        # pilih yang aktivitasnya paling tinggi.
        #
        # Jika level sama, pilih yang paling awal.
        peak_periods.sort(
            key=lambda p: (
                -p["level_num"],
                p["start"]
            )
        )

        starred = peak_periods[0]

    # --------------------------------------------------------
    # Tampilkan semua highest.
    #
    # Kalau starred bukan bagian dari highest,
    # masukkan juga supaya ⭐ tidak muncul pada waktu
    # yang tidak terlihat di RSS.
    # --------------------------------------------------------

    displayed = list(highest_periods)

    if starred is not None:
        if starred not in displayed:
            displayed.append(starred)

    displayed.sort(
        key=lambda p: (
            p["start"],
            p["end"]
        )
    )

    return displayed, starred


# ============================================================
# ASTRONOMICAL FALLBACK
# ============================================================

def astronomical_periods(day):
    """
    Fallback apabila detail HTML tidak berhasil dibaca.

    Ini hanya fallback.
    Star TIDAK dipaksakan di sini.
    """

    result = []

    transit = day.get("transit")
    antitransit = day.get("antitransit")
    moonrise = day.get("moonrise")
    moonset = day.get("moonset")

    if transit:
        result.append({
            "type": "major",
            "level": "sangat tinggi",
            "level_num": 3,
            "start": (
                transit.hour * 60 +
                transit.minute -
                60
            ) % 1440,
            "end": (
                transit.hour * 60 +
                transit.minute +
                60
            ) % 1440,
            "name": "Lunar transit",
            "peak": False,
        })

    if antitransit:
        result.append({
            "type": "major",
            "level": "sangat tinggi",
            "level_num": 3,
            "start": (
                antitransit.hour * 60 +
                antitransit.minute -
                60
            ) % 1440,
            "end": (
                antitransit.hour * 60 +
                antitransit.minute +
                60
            ) % 1440,
            "name": "Opposing lunar transit",
            "peak": False,
        })

    if moonrise:
        result.append({
            "type": "minor",
            "level": "tinggi",
            "level_num": 2,
            "start": (
                moonrise.hour * 60 +
                moonrise.minute -
                30
            ) % 1440,
            "end": (
                moonrise.hour * 60 +
                moonrise.minute +
                30
            ) % 1440,
            "name": "Moonrise",
            "peak": False,
        })

    if moonset:
        result.append({
            "type": "minor",
            "level": "tinggi",
            "level_num": 2,
            "start": (
                moonset.hour * 60 +
                moonset.minute -
                30
            ) % 1440,
            "end": (
                moonset.hour * 60 +
                moonset.minute +
                30
            ) % 1440,
            "name": "Moonset",
            "peak": False,
        })

    return result


# ============================================================
# FETCH
# ============================================================

def fetch_page():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/154.0 Safari/537.36"
        )
    }

    response = requests.get(
        URL,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.text


# ============================================================
# EPHEMERIS
# ============================================================

def compute_days(start_date, count=14):
    if ephem is None:
        raise RuntimeError(
            "Module 'ephem' belum terinstall. "
            "Jalankan: pip install ephem"
        )

    # Koordinat kira-kira Palihan/Yogyakarta.
    # Dipakai hanya untuk fallback astronomi.
    observer = ephem.Observer()

    observer.lat = "-7.80"
    observer.lon = "110.36"

    result = []

    for i in range(count):

        date = start_date + dt.timedelta(days=i)

        observer.date = dt.datetime(
            date.year,
            date.month,
            date.day,
            0,
            0,
            0
        )

        sun = ephem.Sun(observer)
        moon = ephem.Moon(observer)

        try:
            sunrise_ephem = observer.next_rising(
                ephem.Sun(observer)
            )
            sunset_ephem = observer.next_setting(
                ephem.Sun(observer)
            )
        except Exception:
            sunrise_ephem = None
            sunset_ephem = None

        try:
            moonrise_ephem = observer.next_rising(
                ephem.Moon(observer)
            )
            moonset_ephem = observer.next_setting(
                ephem.Moon(observer)
            )
        except Exception:
            moonrise_ephem = None
            moonset_ephem = None

        try:
            transit_ephem = observer.next_transit(
                ephem.Moon(observer)
            )
        except Exception:
            transit_ephem = None

        try:
            antitransit_ephem = observer.next_antitransit(
                ephem.Moon(observer)
            )
        except Exception:
            antitransit_ephem = None

        def convert(value):
            if value is None:
                return None

            d = ephem.Date(value).datetime()

            # UTC -> WIB
            d = d.replace(
                tzinfo=dt.timezone.utc
            ).astimezone(TZ)

            return d

        result.append({
            "date": date,
            "sunrise": convert(sunrise_ephem),
            "sunset": convert(sunset_ephem),
            "moonrise": convert(moonrise_ephem),
            "moonset": convert(moonset_ephem),
            "transit": convert(transit_ephem),
            "antitransit": convert(antitransit_ephem),
        })

    return result


# ============================================================
# FORMATTING
# ============================================================

def _hm(value):
    if value is None:
        return ""

    return value.strftime("%H:%M")


def _win(center, before, after):
    if center is None:
        return None

    start = center - before
    end = center + after

    return (
        _hm(start),
        _hm(end)
    )


def period_text(period, starred=False):
    start = format_minutes(
        period["start"]
    )

    end = format_minutes(
        period["end"]
    )

    star = "⭐ " if starred else ""

    return (
        f"{star}{start}–{end}"
    )


# ============================================================
# FISHING STATUS
# ============================================================

def fishing_status(level):
    mapping = {
        "rendah": ("🔴", "BURUK"),
        "sedang": ("🟡", "SEDANG"),
        "tinggi": ("🟢", "BAGUS"),
        "sangat tinggi": ("🟢", "SANGAT BAGUS"),
    }

    return mapping.get(
        level,
        ("🟡", "SEDANG")
    )


# ============================================================
# RSS ENTRY
# ============================================================

def build_entry(day, fish_level, detailed_periods=None):
    date = day["date"]

    emoji, status = fishing_status(
        fish_level
    )

    # --------------------------------------------------------
    # Detailed Tides4Fishing periods
    # --------------------------------------------------------

    periods = detailed_periods or []

    if not periods:
        periods = astronomical_periods(day)

    displayed, starred = select_best_periods(
        periods,
        day
    )

    time_parts = []

    for period in displayed:

        is_starred = (
            starred is not None
            and period is starred
        )

        time_parts.append(
            period_text(
                period,
                starred=is_starred
            )
        )

    times = ", ".join(time_parts)

    title = (
        f"{emoji} "
        f"{date.day} {ID_MONTHS[date.month - 1][:3]} "
        f"| {status}"
    )

    if times:
        title += f" | {times}"

    # --------------------------------------------------------
    # Description
    # --------------------------------------------------------

    description_parts = [
        f"Aktivitas ikan: {status}"
    ]

    if day.get("sunrise"):
        description_parts.append(
            f"Sunrise: {_hm(day['sunrise'])}"
        )

    if day.get("sunset"):
        description_parts.append(
            f"Sunset: {_hm(day['sunset'])}"
        )

    if day.get("moonrise"):
        description_parts.append(
            f"Moonrise: {_hm(day['moonrise'])}"
        )

    if day.get("moonset"):
        description_parts.append(
            f"Moonset: {_hm(day['moonset'])}"
        )

    description = " | ".join(
        description_parts
    )

    return {
        "title": title,
        "description": description,
        "date": date,
    }


# ============================================================
# RSS WRITER
# ============================================================

def xml_escape(value):
    if value is None:
        return ""

    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def write_feed(entries, filename):
    now = dt.datetime.now(TZ)

    rss = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "<channel>",
        "<title>Palihan Fishing Activity</title>",
        f"<link>{xml_escape(URL)}</link>",
        "<description>Aktivitas ikan Palihan</description>",
        f"<lastBuildDate>{now.strftime('%a, %d %b %Y %H:%M:%S %z')}</lastBuildDate>",
    ]

    for entry in entries:

        pub_date = dt.datetime.combine(
            entry["date"],
            dt.time(
                6,
                0
            ),
            tzinfo=TZ
        )

        rss.extend([
            "<item>",
            f"<title>{xml_escape(entry['title'])}</title>",
            f"<description>{xml_escape(entry['description'])}</description>",
            f"<pubDate>{pub_date.strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>",
            f"<guid>{entry['date'].isoformat()}</guid>",
            "</item>",
        ])

    rss.extend([
        "</channel>",
        "</rss>",
    ])

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(
            "\n".join(rss)
        )


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output",
        default="palihan.xml"
    )

    parser.add_argument(
        "--days",
        type=int,
        default=14
    )

    args = parser.parse_args()

    print("Mengambil halaman Tides4Fishing...")

    html = fetch_page()

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    print("Parsing aktivitas ikan...")

    coefficients = parse_coefficients(
        soup
    )

    fish_activity = parse_solunar(
        soup
    )

    print("Parsing periode solunar detail...")

    detailed_periods = parse_detailed_periods(
        soup
    )

    print(
        f"Ditemukan {len(detailed_periods)} "
        "periode detail."
    )

    today = dt.datetime.now(
        TZ
    ).date()

    days = compute_days(
        today,
        args.days
    )

    entries = []

    for index, day in enumerate(days):

        date = day["date"]

        fish = fish_activity.get(
            date.day
        )

        if fish:
            fish_level = fish["level"]
        else:
            # fallback berdasarkan coefficient
            coeff = coefficients.get(
                date.day
            )

            if coeff:
                status = coeff["status"].lower()

                if "very high" in status:
                    fish_level = "sangat tinggi"
                elif "high" in status:
                    fish_level = "tinggi"
                elif (
                    "average" in status
                    or "medium" in status
                ):
                    fish_level = "sedang"
                else:
                    fish_level = "rendah"
            else:
                fish_level = "sedang"

        # ----------------------------------------------------
        # Halaman utama hanya memberikan detail periode
        # untuk hari yang sedang dibuka.
        #
        # Jadi detail periode HTML dipakai untuk hari pertama.
        # Hari berikutnya menggunakan fallback astronomi.
        # ----------------------------------------------------

        if index == 0:
            periods = detailed_periods
        else:
            periods = []

        entry = build_entry(
            day,
            fish_level,
            periods
        )

        entries.append(entry)

        print(
            entry["title"]
        )

    write_feed(
        entries,
        args.output
    )

    print()
    print(
        f"RSS berhasil dibuat: {args.output}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
