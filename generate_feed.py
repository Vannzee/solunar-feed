import datetime
import re
from zoneinfo import ZoneInfo
import ephem
from feedgen.feed import FeedGenerator
import requests
from bs4 import BeautifulSoup

fg = FeedGenerator()
fg.title("Solunar Palihan")
fg.link(href="https://tides4fishing.com/id/yogyakarta/palihan", rel="alternate")
fg.description("Prediksi jam makan ikan pantai selatan")
fg.language("id")

tz = ZoneInfo("Asia/Jakarta")
observer = ephem.Observer()
observer.lat = "-7.91"  # Palihan, Kulon Progo
observer.lon = "110.07"
observer.elevation = 5

now_time = datetime.datetime.now(tz)
today = now_time.date()

HARI_INDO = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
BULAN_INDO = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"]

STATUS_MAP = {
    "very high": "sangat tinggi",
    "high": "tinggi",
    "average": "sedang",
    "low": "rendah",
    "muy alta": "sangat tinggi",
    "alta": "tinggi",
    "media": "sedang",
    "baja": "rendah",
}

# 1. Scrape data koefisien & status langsung dari tabel web Tides4fishing
live_coefficients = {}
try:
    url = "https://tides4fishing.com/id/yogyakarta/palihan"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "id,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=20)
    if resp.status_code == 200:
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Cari baris tabel pasang surut harian
        rows = soup.find_all(lambda tag: tag.name == "tr" and tag.get("id", "").startswith("tabla_mareas_dia_"))
        for row in rows:
            row_id = row.get("id", "")
            # Ambil nomor hari dari ID elemen (contoh: tabla_mareas_dia_6 -> 6)
            match_day = re.search(r"tabla_mareas_dia_(\d+)", row_id)
            if not match_day:
                continue
            day_num = int(match_day.group(1))

            # Ekstrak angka koefisien dan status teks di kolom koefisien
            coef_cell = row.find(class_=re.compile(r"coeficiente|col_coeficiente", re.I))
            cell_text = coef_cell.get_text(" ", strip=True) if coef_cell else row.get_text(" ", strip=True)
            
            # Cari pola angka koefisien (misal 69, 81, 91) diikuti status
            m_val = re.search(r"\b(\d{2,3})\b\s*(very high|high|average|low|muy alta|alta|media|baja)?", cell_text, re.I)
            if m_val:
                val = m_val.group(1)
                raw_stat = (m_val.group(2) or "").lower()
                status_indo = STATUS_MAP.get(raw_stat, "sedang")
                live_coefficients[day_num] = f"{val} ({status_indo})"
except Exception:
    pass

# 2. Generate entri feed untuk 14 hari ke depan
JUMLAH_HARI = 14

for i in range(JUMLAH_HARI):
    target_date = today + datetime.timedelta(days=i)
    observer.date = target_date.strftime("%Y/%m/%d")

    moon = ephem.Moon()
    moon.compute(observer)
    m_transit = ephem.localtime(observer.next_transit(moon)).astimezone(tz)
    m_antitransit = ephem.localtime(observer.next_antitransit(moon)).astimezone(tz)
    m_rise = ephem.localtime(observer.next_rising(moon)).astimezone(tz)
    m_set = ephem.localtime(observer.next_setting(moon)).astimezone(tz)

    day_num = target_date.day
    # Gunakan hasil scrape langsung dari tabel web
    if day_num in live_coefficients:
        activity_text = live_coefficients[day_num]
    else:
        # Fallback cadangan jika koneksi web gagal
        phase = moon.moon_phase
        activity_text = "90 (sangat tinggi)" if (phase <= 0.15 or phase >= 0.85) else "55 (sedang)"

    nama_hari = HARI_INDO[target_date.weekday()]
    nama_bulan = BULAN_INDO[target_date.month]
    tanggal_str = f"{nama_hari}, {target_date.day:02d} {nama_bulan}"
    date_label = "Hari ini" if i == 0 else tanggal_str

    title = f"{date_label} | Aktivitas Ikan: {activity_text} | Major: {m_transit.strftime('%H:%M')} & {m_antitransit.strftime('%H:%M')}"

    desc = (
        f"<b>Koefisien Pasang Surut:</b> {activity_text}<br><br>"
        f"<b>Waktu Utama (Major):</b><br>"
        f"• { (m_transit - datetime.timedelta(hours=1)).strftime('%H:%M') } - { (m_transit + datetime.timedelta(hours=1)).strftime('%H:%M') }<br>"
        f"• { (m_antitransit - datetime.timedelta(hours=1)).strftime('%H:%M') } - { (m_antitransit + datetime.timedelta(hours=1)).strftime('%H:%M') }<br><br>"
        f"<b>Waktu Tambahan (Minor):</b><br>"
        f"• { (m_rise - datetime.timedelta(minutes=30)).strftime('%H:%M') } - { (m_rise + datetime.timedelta(minutes=30)).strftime('%H:%M') } (Terbit)<br>"
        f"• { (m_set - datetime.timedelta(minutes=30)).strftime('%H:%M') } - { (m_set + datetime.timedelta(minutes=30)).strftime('%H:%M') } (Terbenam)"
    )

    fe = fg.add_entry()
    fe.id(f"palihan-{target_date.isoformat()}")
    fe.title(title)
    fe.link(href="https://tides4fishing.com/id/yogyakarta/palihan")
    fe.description(desc)
    
    # Inversi waktu pubDate agar urutan "Hari ini" selalu paling atas
    fe.pubDate(now_time - datetime.timedelta(hours=i))

fg.rss_file("palihan.xml", pretty=True)
