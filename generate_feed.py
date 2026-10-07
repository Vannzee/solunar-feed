"""
Solunar Palihan - RSS generator (versi gabungan saja).

Menulis SATU feed: palihan.xml, berisi koefisien pasang surut + aktivitas solunar
dalam dua kolom. Nama file sama dengan sebelumnya, jadi link RSS dan workflow lama
tidak perlu diubah.

Pakai:  python generate_feed.py [--sample page.html]
"""
import argparse
import datetime
import re
import traceback
from collections import Counter
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

URL = "https://tides4fishing.com/id/yogyakarta/palihan"
TZ = ZoneInfo("Asia/Jakarta")
UTC = datetime.timezone.utc
H1, M30 = datetime.timedelta(hours=1), datetime.timedelta(minutes=30)

HARI_INDO = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
BULAN_INDO = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]

LEVELS_ID = ["rendah", "sedang", "tinggi", "sangat tinggi"]  # urut dari 0 sampai 3
STATUS_MAP = {
    "very high": "sangat tinggi", "high": "tinggi", "average": "sedang", "low": "rendah",
    "muy alta": "sangat tinggi", "alta": "tinggi", "media": "sedang", "baja": "rendah",
    "sangat tinggi": "sangat tinggi", "tinggi": "tinggi", "sedang": "sedang", "rendah": "rendah",
}
LEVEL = r"very high|muy alta|sangat tinggi|high|average|low|alta|media|baja|tinggi|sedang|rendah"

# ---------------------------------------------------------------- scraping

ROW = re.compile(
    r"\b(\d{1,2})\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b"
    r"(?:(?!\b\d{1,2}\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b).){0,160}?"
    r"\b(\d{1,3})\s+(" + LEVEL + r")\b",
    re.I,
)
DAYROW = re.compile(r"^(\d{1,2})\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", re.I)
COEF_CELL = re.compile(r"^\d{1,3}\s+(?:" + LEVEL + r")$", re.I)
LEVEL_ONLY = re.compile(r"\b(" + LEVEL + r")\b", re.I)


def flatten(html: str) -> str:
    if "</" in html:
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style"]):
            t.decompose()
        html = soup.get_text(" ")
    return re.sub(r"\s+", " ", html)


def month_year_of_table(text: str, today: datetime.date):
    start = text.lower().find("tide table")
    scope = text[start:start + 6000] if start != -1 else text[:6000]
    hits = re.findall(r"\b(" + "|".join(MONTHS_EN) + r")\s*,?\s*(20\d\d)\b", scope, re.I)
    if not hits:
        return today.year, today.month
    (mon, yr), _ = Counter((m.capitalize(), y) for m, y in hits).most_common(1)[0]
    return int(yr), MONTHS_EN.index(mon) + 1


def parse_coefficients(text: str, today: datetime.date) -> dict:
    """{date: 'koef (status)'} dari kolom COEFFICIENT."""
    year, month = month_year_of_table(text, today)
    out = {}
    for m in ROW.finditer(text):
        day, val, raw = int(m.group(1)), m.group(2), m.group(3).lower()
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            continue
        out.setdefault(d, f"{val} ({STATUS_MAP.get(raw, raw)})")
    return out


def parse_solunar(html: str, today: datetime.date):
    """
    {date: level} dari kolom SOLUNAR ACTIVITY pada tabel bulanan, plus contoh HTML satu baris
    untuk diagnosa. Hanya membaca sel yang TEPAT SETELAH sel koefisien dan hanya kalau sel itu
    memuat kata level (teks, alt, title, aria-label). Tidak pernah memakai nilai koefisien.
    """
    out, sample = {}, None
    if "</" not in html:
        return out, sample
    year, month = month_year_of_table(flatten(html), today)
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        text = " ".join(tr.get_text(" ").split())
        m = DAYROW.match(text)
        if not m:
            continue
        cells = tr.find_all(["td", "th"])
        idx = next((i for i, c in enumerate(cells)
                    if COEF_CELL.match(" ".join(c.get_text(" ").split()))), None)
        if idx is None or idx + 1 >= len(cells):
            continue
        if sample is None:
            sample = str(tr)[:1500]
        cell = cells[idx + 1]
        hints = [cell.get_text(" ")]
        hints += [str(t.get(a, "")) for t in cell.find_all(True) for a in ("alt", "title", "aria-label")]
        hints += [str(cell.get(a, "")) for a in ("title", "aria-label")]
        lm = LEVEL_ONLY.search(" ".join(hints))
        if not lm:
            continue
        try:
            d = datetime.date(year, month, int(m.group(1)))
        except ValueError:
            continue
        out.setdefault(d, STATUS_MAP[lm.group(1).lower()])
    return out, sample


def fetch_page(sample_file=None):
    if sample_file:
        return open(sample_file, encoding="utf-8").read()
    try:
        resp = requests.get(
            URL, timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                     "Accept-Language": "en;q=0.9"},
        )
        print(f"[scrape] HTTP {resp.status_code}, {len(resp.text)} karakter")
        if resp.status_code != 200:
            print("[scrape] respons awal:", resp.text[:300].replace("\n", " "))
            return None
        return resp.text
    except Exception:
        print("[scrape] ERROR:")
        traceback.print_exc()
        return None


# ------------------------------------------------------- astronomi (ephem)

def compute_days(today: datetime.date, n: int = 14):
    """
    Waktu bulan/matahari per hari. Jendela hari = 00:00-24:00 WIB. (Skrip lama memakai
    '2026/10/07' yang berarti 00:00 UTC = 07:00 WIB, sehingga kejadian dini hari
    jatuh ke hari berikutnya.)
    """
    import ephem

    obs = ephem.Observer()
    obs.lat, obs.lon, obs.elevation = "-7.91", "110.07", 5  # Palihan, Kulon Progo
    days = []
    for i in range(n):
        d = today + datetime.timedelta(days=i)
        start = datetime.datetime.combine(d, datetime.time(0), tzinfo=TZ)
        end = start + datetime.timedelta(days=1)
        obs.date = start.astimezone(UTC).replace(tzinfo=None)

        def ev(fn, body):
            try:
                t = fn(body)
            except (ephem.NeverUpError, ephem.AlwaysUpError):
                return None
            dt = ephem.Date(t).datetime().replace(tzinfo=UTC).astimezone(TZ)
            return dt if start <= dt < end else None

        moon, sun = ephem.Moon(), ephem.Sun()
        ref = ephem.Date(float(obs.date) + 0.5)  # tengah hari
        dist = min(abs(float(ref) - float(f(ref))) for f in (
            ephem.previous_new_moon, ephem.next_new_moon,
            ephem.previous_full_moon, ephem.next_full_moon))
        days.append({
            "date": d, "dist": dist,
            "transit": ev(obs.next_transit, moon), "anti": ev(obs.next_antitransit, moon),
            "rise": ev(obs.next_rising, moon), "set": ev(obs.next_setting, moon),
            "sunrise": ev(obs.next_rising, sun), "sunset": ev(obs.next_setting, sun),
        })
    return days


def estimate_solunar(day: dict) -> int:
    """
    PERKIRAAN sendiri (0-3), dipakai hanya kalau situs tidak terbaca.
    Dasar: jarak ke bulan baru/purnama (teori solunar: terkuat di sekitar keduanya),
    +1 bila periode major/minor bertepatan dengan matahari terbit/terbenam.
    Ambang batas adalah heuristik, BUKAN rumus tides4fishing.
    """
    dist = day["dist"]
    base = 2 if dist <= 2 else 1 if dist <= 5.5 else 0
    periods = [(t - H1, t + H1) for t in (day["transit"], day["anti"]) if t]
    periods += [(t - M30, t + M30) for t in (day["rise"], day["set"]) if t]
    suns = [(t - M30, t + M30) for t in (day["sunrise"], day["sunset"]) if t]
    bonus = any(a0 < b1 and b0 < a1 for a0, a1 in periods for b0, b1 in suns)
    return min(3, base + (1 if bonus else 0))


# ----------------------------------------------------------- format entri

def _hm(t):
    return t.strftime("%H:%M") if t else "-"


def _win(t, delta):
    return f"{_hm(t - delta)} - {_hm(t + delta)}" if t else "-"


def build_entry(i, day, coef, sol, from_site):
    """
    Kembalikan (title, description_html).
    sol: teks level Indonesia; from_site: True bila dari tabel situs, False bila perkiraan (diberi tanda ≈).
    """
    d = day["date"]
    label = "Hari ini" if i == 0 else f"{HARI_INDO[d.weekday()]}, {d.day:02d} {BULAN_INDO[d.month]}"
    major = f"Major: {_hm(day['transit'])} & {_hm(day['anti'])}"
    sol_txt = sol if from_site else f"≈{sol}"
    sol_note = "dari tabel tides4fishing" if from_site else "perkiraan hitung sendiri (data situs tidak terbaca)"

    title = f"{label} | Koef {coef or '-'} · Solunar {sol_txt} | {major}"
    desc = (
        "<table border='1' cellpadding='4' cellspacing='0'>"
        "<tr><th>Koefisien pasang surut</th><th>Aktivitas solunar</th></tr>"
        f"<tr><td>{coef or '-'}</td><td>{sol_txt}</td></tr></table>"
        f"<i>Solunar: {sol_note}</i><br><br>"
        f"<b>Waktu Utama (Major):</b><br>"
        f"• {_win(day['transit'], H1)}<br>• {_win(day['anti'], H1)}<br><br>"
        f"<b>Waktu Tambahan (Minor):</b><br>"
        f"• {_win(day['rise'], M30)} (Terbit)<br>• {_win(day['set'], M30)} (Terbenam)"
    )
    return title, desc


def write_feed(path, days, coefs, site_sol, now_time):
    from feedgen.feed import FeedGenerator

    fg = FeedGenerator()
    fg.title("Solunar Palihan")
    fg.link(href=URL, rel="alternate")
    fg.description("Prediksi jam makan ikan pantai selatan: koefisien pasang surut + aktivitas solunar")
    fg.language("id")

    for i, day in enumerate(days):
        d = day["date"]
        from_site = d in site_sol
        sol = site_sol[d] if from_site else LEVELS_ID[estimate_solunar(day)]
        title, desc = build_entry(i, day, coefs.get(d), sol, from_site)
        fe = fg.add_entry()
        fe.id(f"palihan-{d.isoformat()}")
        fe.title(title)
        fe.link(href=URL)
        fe.description(desc)
        fe.pubDate(now_time - datetime.timedelta(hours=i))
    fg.rss_file(path, pretty=True)
    print(f"[feed] {path} ditulis")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="file HTML tersimpan untuk pengujian")
    a = ap.parse_args()

    now_time = datetime.datetime.now(TZ)
    today = now_time.date()

    raw = fetch_page(a.sample)
    coefs, site_sol = {}, {}
    if raw:
        coefs = parse_coefficients(flatten(raw), today)
        site_sol, sample_row = parse_solunar(raw, today)
        print(f"[scrape] koefisien: {len(coefs)} hari | solunar dari situs: {len(site_sol)} hari")
        if not coefs:
            print("[scrape] PERINGATAN: koefisien tidak terbaca - layout situs berubah / diblokir")
        if not site_sol:
            print("[scrape] solunar situs tidak terbaca -> pakai perkiraan sendiri (tanda ≈)")
            print("[scrape] contoh baris tabel untuk diagnosa:", sample_row or "(tidak ada baris tabel)")

    write_feed("palihan.xml", compute_days(today), coefs, site_sol, now_time)


if __name__ == "__main__":
    main()
