import datetime
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

fg = FeedGenerator()
fg.title("Solunar Palihan")
fg.link(href="https://tides4fishing.com/id/yogyakarta/palihan", rel="alternate")
fg.description("Prediksi jam makan ikan pantai selatan")
fg.language("id")

tz = ZoneInfo("Asia/Jakarta")
now_time = datetime.datetime.now(tz)
today = now_time.date()

url = "https://tides4fishing.com/id/yogyakarta/palihan"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

resp = requests.get(url, headers=headers, timeout=15)
soup = BeautifulSoup(resp.text, "html.parser")

HARI_INDO = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
BULAN_INDO = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"]

# Cari baris-baris tabel pasang surut / solunar
rows = soup.select("table.tabla_mareas tr[id^='tabla_mareas_dia_']")

item_count = 0
for row in rows:
    if item_count >= 5:
        break

    # 1. Hitung jumlah ikon ikan langsung dari kolom solunar
    fish_icons = row.select(".col_actividad .icono_pez, .col_actividad img[src*='pez']")
    n_fish = len(fish_icons)
    if n_fish == 0:
        # Fallback jika class SVG/CSS berbeda
        act_text = row.text.lower()
        if "very high" in act_text or "muy alta" in act_text:
            n_fish = 3
        elif "high" in act_text or "alta" in act_text:
            n_fish = 2
        else:
            n_fish = 1

    icon_str = "🐟" * (n_fish if n_fish > 0 else 1)

    # 2. Tanggal target
    target_date = today + datetime.timedelta(days=item_count)
    nama_hari = HARI_INDO[target_date.weekday()]
    nama_bulan = BULAN_INDO[target_date.month]
    tanggal_str = f"{nama_hari}, {target_date.day:02d} {nama_bulan}"
    date_label = "Hari ini" if item_count == 0 else tanggal_str

    # 3. Format judul sesuai request: Hari/Tgl | Ikon | Major
    title = f"{date_label} | {icon_str} | Major"

    fe = fg.add_entry()
    fe.id(f"palihan-{target_date.isoformat()}")
    fe.title(title)
    fe.link(href="https://tides4fishing.com/id/yogyakarta/palihan")
    fe.description(f"Aktivitas Ikan: {icon_str} (Tidal Coefficient & Solunar Match)")
    
    # Inversi waktu pubDate agar entri 'Hari ini' berada di baris paling atas
    fe.pubDate(now_time - datetime.timedelta(hours=item_count))
    item_count += 1

fg.rss_file("palihan.xml", pretty=True)
