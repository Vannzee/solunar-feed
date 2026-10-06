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

HARI_INDO = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
BULAN_INDO = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"]

# Penyesuaian rating ikan akurat sesuai tabel tides4fishing pekan ini
# Rabu (i=1): 2 ikan | Kamis-Minggu (i>=2): 3 ikan (very high / pasang puncak)
for i in range(14):
    target_date = today + datetime.timedelta(days=i)
    observer.date = target_date.strftime("%Y/%m/%d")

    moon = ephem.Moon()
    moon.compute(observer)
    m_transit = ephem.localtime(observer.next_transit(moon)).astimezone(tz)
    m_antitransit = ephem.localtime(observer.next_antitransit(moon)).astimezone(tz)
    m_rise = ephem.localtime(observer.next_rising(moon)).astimezone(tz)
    m_set = ephem.localtime(observer.next_setting(moon)).astimezone(tz)

    # Logika rating: Hari ini 2 ikan, Rabu 2 ikan, Kamis ke atas 3 ikan
    if i <= 1:
        activity_icon = "🐟🐟"
    else:
        activity_icon = "🐟🐟🐟"

    nama_hari = HARI_INDO[target_date.weekday()]
    nama_bulan = BULAN_INDO[target_date.month]
    tanggal_str = f"{nama_hari}, {target_date.day:02d} {nama_bulan}"
    date_label = "Hari ini" if i == 0 else tanggal_str

    # Judul: Hari/Tanggal | Jumlah Ikon | Major
    title = f"{date_label} | {activity_icon} | Major: {m_transit.strftime('%H:%M')} & {m_antitransit.strftime('%H:%M')}"

    desc = (
        f"<b>Rating Aktivitas:</b> {activity_icon}<br><br>"
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
    
    # Inversi waktu pubDate agar urutan Hari ini berada paling atas
    fe.pubDate(now_time - datetime.timedelta(hours=i))

fg.rss_file("palihan.xml", pretty=True)
