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

today = datetime.datetime.now(tz).date()

for i in range(4, -1, -1):  # Buat entri untuk 5 hari ke depan
  target_date = today + datetime.timedelta(days=i)
  observer.date = target_date.strftime("%Y/%m/%d")

  moon = ephem.Moon()
  m_transit = ephem.localtime(observer.next_transit(moon)).astimezone(tz)
  m_antitransit = ephem.localtime(observer.next_antitransit(moon)).astimezone(tz)
  m_rise = ephem.localtime(observer.next_rising(moon)).astimezone(tz)
  m_set = ephem.localtime(observer.next_setting(moon)).astimezone(tz)

  # Format ringkas yang muat di kartu widget
  date_label = "Hari ini" if i == 0 else target_date.strftime("%a, %d %b")
  title = f"🐟 {date_label} | Major: {m_transit.strftime('%H:%M')} & {m_antitransit.strftime('%H:%M')}"

  desc = (
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
  fe.pubDate(
      datetime.datetime.combine(target_date, datetime.time(0, 0), tzinfo=tz)
  )

fg.rss_file("palihan.xml", pretty=True)
