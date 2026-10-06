import datetime
from zoneinfo import ZoneInfo
import ephem
from feedgen.feed import FeedGenerator

fg = FeedGenerator()
fg.title("Solunar Palihan")
fg.link(
    href="https://tides4fishing.com/id/yogyakarta/palihan", rel="alternate"
)
fg.description("Prediksi jam makan ikan pantai selatan")
fg.language("id")

tz = ZoneInfo("Asia/Jakarta")
observer = ephem.Observer()
observer.lat = "-7.91"  # Palihan, Kulon Progo
observer.lon = "110.07"
observer.elevation = 5

now_time = datetime.datetime.now(tz)
today = now_time.date()

# Kamus nama hari dan bulan bahasa Indonesia
HARI_INDO = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
BULAN_INDO = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"]

for i in range(5):  # Buat entri untuk 5 hari ke depan
    target_date = today + datetime.timedelta(days=i)
    observer.date = target_date.strftime("%Y/%m/%d")

    moon = ephem.Moon()
    moon.compute(observer)
    m_transit = ephem.localtime(observer.next_transit(moon)).astimezone(tz)
    m_antitransit = ephem.localtime(observer.next_antitransit(moon)).astimezone(tz)
    m_rise = ephem.localtime(observer.next_rising(moon)).astimezone(tz)
    m_set = ephem.localtime(observer.next_setting(moon)).astimezone(tz)

    # Estimasi rating aktivitas dari fase bulan (Bulan Baru / Purnama = 3 Ikan)
    phase = moon.moon_phase  # 0.0 s/d 1.0
    if phase <= 0.15 or phase >= 0.85:
        activity_icon = "🐟🐟🐟"
        activity_label = "Sangat Tinggi (Very High)"
    elif 0.35 <= phase <= 0.65:
        activity_icon = "🐟"
        activity_label = "Rendah (Low)"
    else:
        activity_icon = "🐟🐟"
        activity_label = "Sedang (Average/High)"

    # Format nama hari & tanggal bahasa Indonesia
    nama_hari = HARI_INDO[target_date.weekday()]
    nama_bulan = BULAN_INDO[target_date.month]
    tanggal_str = f"{nama_hari}, {target_date.day:02d} {nama_bulan}"
    date_label = "Hari ini" if i == 0 else tanggal_str

    # Format judul: Hari/Tanggal | Jumlah Ikon | Major
    title = f"{date_label} | {activity_icon} | Major: {m_transit.strftime('%H:%M')} & {m_antitransit.strftime('%H:%M')}"

    desc = (
        f"<b>Rating Aktivitas:</b> {activity_icon} ({activity_label})<br><br>"
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
    
    # Inversi waktu pubDate agar urutan "Hari ini" selalu di atas
    fe.pubDate(now_time - datetime.timedelta(hours=i))

fg.rss_file("palihan.xml", pretty=True)
