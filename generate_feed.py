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

# Data koefisien pasang surut asli dari tabel Tides4fishing Palihan
DATA_KOEFISIEN = {
    6:  (60, "sedang"),
    7:  (81, "tinggi"),
    8:  (91, "sangat tinggi"),
    9:  (95, "sangat tinggi"),
    10: (96, "sangat tinggi"),
    11: (92, "sangat tinggi"),
    12: (85, "tinggi"),
    13: (76, "tinggi"),
    14: (65, "sedang"),
    15: (53, "sedang"),
    16: (41, "rendah"),
    17: (32, "rendah"),
    18: (28, "rendah"),
    19: (32, "rendah"),
}

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
    if day_num in DATA_KOEFISIEN:
        coef, status = DATA_KOEFISIEN[day_num]
    else:
        coef, status = (50, "sedang")

    activity_text = f"{coef} ({status})"

    nama_hari = HARI_INDO[target_date.weekday()]
    nama_bulan = BULAN_INDO[target_date.month]
    tanggal_str = f"{nama_hari}, {target_date.day:02d} {nama_bulan}"
    date_label = "Hari ini" if i == 0 else tanggal_str

    # Format: Hari atau tanggal | Aktivitas Ikan: [angka] (status) | Major: jam
    title = f"{date_label} | Aktivitas Ikan: {activity_text} | Major: {m_transit.strftime('%H:%M')} & {m_antitransit.strftime('%H:%M')}"

    desc = (
        f"<b>Koefisien Pasang Surut:</b> {coef} ({status})<br><br>"
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
    
    # Inversi waktu pubDate agar urutan Hari ini selalu paling atas di widget
    fe.pubDate(now_time - datetime.timedelta(hours=i))

fg.rss_file("palihan.xml", pretty=True)
