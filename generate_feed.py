import datetime
import re
import sys
import traceback
from collections import Counter
from zoneinfo import ZoneInfo

import ephem
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

URL = "https://tides4fishing.com/id/yogyakarta/palihan"
TZ = ZoneInfo("Asia/Jakarta")

HARI_INDO = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
BULAN_INDO = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]

STATUS_MAP = {
    "very high": "sangat tinggi", "high": "tinggi", "average": "sedang", "low": "rendah",
    "muy alta": "sangat tinggi", "alta": "tinggi", "media": "sedang", "baja": "rendah",
    "sangat tinggi": "sangat tinggi", "tinggi": "tinggi", "sedang": "sedang", "rendah": "rendah",
}

# Satu baris tabel: "6 Tue 5:22 h 17:34 h 4:57 h 1.5 m ... 69 average"
# Tidak bergantung pada id/class HTML, hanya pada teks tabel. Bagian tengah dilarang
# memuat awal baris lain supaya tidak "meminjam" koefisien dari baris berikutnya.
ROW = re.compile(
    r"\b(\d{1,2})\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b"
    r"(?:(?!\b\d{1,2}\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b).){0,160}?"
    r"\b(\d{1,3})\s+(very high|high|average|low|muy alta|alta|media|baja|sangat tinggi|tinggi|sedang|rendah)\b",
    re.I,
)


def flatten(html: str) -> str:
    """HTML -> satu baris teks. Teks biasa juga boleh (untuk pengujian)."""
    if "</" in html:
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style"]):
            t.decompose()
        html = soup.get_text(" ")
    return re.sub(r"\s+", " ", html)


def month_year_of_table(text: str, today: datetime.date):
    """Bulan tabel = bulan yang paling sering disebut di sekitar judul tabel."""
    start = text.lower().find("tide table")
    scope = text[start:start + 6000] if start != -1 else text[:6000]
    hits = re.findall(r"\b(" + "|".join(MONTHS_EN) + r")\s*,?\s*(20\d\d)\b", scope, re.I)
    if not hits:
        return today.year, today.month
    (mon, yr), _ = Counter((m.capitalize(), y) for m, y in hits).most_common(1)[0]
    return int(yr), MONTHS_EN.index(mon) + 1


def parse_coefficients(text: str, today: datetime.date) -> dict:
    """Kembalikan {date: 'koef (status)'}. Kunci pakai tanggal LENGKAP, bukan nomor hari."""
    year, month = month_year_of_table(text, today)
    out = {}
    for m in ROW.finditer(text):
        day, val, raw = int(m.group(1)), m.group(2), m.group(3).lower()
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            continue
        out.setdefault(d, f"{val} ({STATUS_MAP.get(raw, raw)})")  # baris pertama menang
    return out


def fetch_coefficients(today: datetime.date, sample_file: str | None = None) -> dict:
    try:
        if sample_file:
            raw = open(sample_file, encoding="utf-8").read()
        else:
            resp = requests.get(
                URL, timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept-Language": "en;q=0.9",
                },
            )
            print(f"[scrape] HTTP {resp.status_code}, {len(resp.text)} karakter")
            if resp.status_code != 200:
                print("[scrape] respons awal:", resp.text[:300].replace("\n", " "))
                return {}
            raw = resp.text
        coefs = parse_coefficients(flatten(raw), today)
        print(f"[scrape] koefisien ditemukan untuk {len(coefs)} hari")
        if not coefs:
            print("[scrape] PERINGATAN: tabel tidak terbaca - layout situs mungkin berubah / diblokir")
        return coefs
    except Exception:
        print("[scrape] ERROR:")
        traceback.print_exc()
        return {}


def main():
    sample = sys.argv[1] if len(sys.argv) > 1 else None

    fg = FeedGenerator()
    fg.title("Solunar Palihan")
    fg.link(href=URL, rel="alternate")
    fg.description("Prediksi jam makan ikan pantai selatan")
    fg.language("id")

    observer = ephem.Observer()
    observer.lat = "-7.91"  # Palihan, Kulon Progo
    observer.lon = "110.07"
    observer.elevation = 5

    now_time = datetime.datetime.now(TZ)
    today = now_time.date()
    coefs = fetch_coefficients(today, sample)

    for i in range(14):
        target_date = today + datetime.timedelta(days=i)
        observer.date = target_date.strftime("%Y/%m/%d")

        moon = ephem.Moon()
        moon.compute(observer)
        m_transit = ephem.localtime(observer.next_transit(moon)).astimezone(TZ)
        m_antitransit = ephem.localtime(observer.next_antitransit(moon)).astimezone(TZ)
        m_rise = ephem.localtime(observer.next_rising(moon)).astimezone(TZ)
        m_set = ephem.localtime(observer.next_setting(moon)).astimezone(TZ)

        # Tidak ada angka karangan lagi: kalau hari ini tidak ada di tabel, koefisien dikosongkan.
        coef = coefs.get(target_date)
        coef_title = f"Aktivitas Ikan: {coef} | " if coef else ""
        coef_desc = f"<b>Aktivitas Ikan:</b> {coef}<br><br>" if coef else ""

        tanggal_str = f"{HARI_INDO[target_date.weekday()]}, {target_date.day:02d} {BULAN_INDO[target_date.month]}"
        date_label = "Hari ini" if i == 0 else tanggal_str

        title = f"{date_label} | {coef_title}Major: {m_transit:%H:%M} & {m_antitransit:%H:%M}"
        hm = lambda d: d.strftime("%H:%M")
        h1, m30 = datetime.timedelta(hours=1), datetime.timedelta(minutes=30)
        desc = (
            f"{coef_desc}"
            f"<b>Waktu Utama (Major):</b><br>"
            f"• {hm(m_transit - h1)} - {hm(m_transit + h1)}<br>"
            f"• {hm(m_antitransit - h1)} - {hm(m_antitransit + h1)}<br><br>"
            f"<b>Waktu Tambahan (Minor):</b><br>"
            f"• {hm(m_rise - m30)} - {hm(m_rise + m30)} (Terbit)<br>"
            f"• {hm(m_set - m30)} - {hm(m_set + m30)} (Terbenam)"
        )

        fe = fg.add_entry()
        fe.id(f"palihan-{target_date.isoformat()}")
        fe.title(title)
        fe.link(href=URL)
        fe.description(desc)
        fe.pubDate(now_time - datetime.timedelta(hours=i))  # "Hari ini" tetap paling atas

    fg.rss_file("palihan.xml", pretty=True)


if __name__ == "__main__":
    main()
