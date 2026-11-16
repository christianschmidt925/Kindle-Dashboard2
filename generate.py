import json
import calendar
import re
import sys
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import feedparser
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
WIDTH = 1072
HEIGHT = 1448
LATITUDE = 48.137
LONGITUDE = 11.576
TIMEZONE = "Europe/Berlin"
RSS_FEEDS = (
    ("WELT", "https://www.tagesschau.de/ausland/index~rss2.xml"),
    ("DEUTSCHLAND", "https://www.tagesschau.de/inland/index~rss2.xml"),
)
MUNICH_FEEDS = (
    "https://www.br.de/nachrichten/oberbayern/index~rss2.xml",
    "https://rss.sueddeutsche.de/rss/Muenchen",
)

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

WEATHER = {
    0: ("Sonnig", "sun"),
    1: ("Überwiegend sonnig", "sun"),
    2: ("Teilweise bewölkt", "cloud"),
    3: ("Bewölkt", "cloud"),
    45: ("Neblig", "fog"),
    48: ("Nebel mit Reif", "fog"),
    51: ("Leichter Nieselregen", "rain"),
    53: ("Nieselregen", "rain"),
    55: ("Starker Nieselregen", "rain"),
    56: ("Gefrierender Nieselregen", "rain"),
    57: ("Starker gefrierender Nieselregen", "rain"),
    61: ("Leichter Regen", "rain"),
    63: ("Regen", "rain"),
    65: ("Starker Regen", "rain"),
    66: ("Gefrierender Regen", "rain"),
    67: ("Starker gefrierender Regen", "rain"),
    71: ("Leichter Schneefall", "snow"),
    73: ("Schneefall", "snow"),
    75: ("Starker Schneefall", "snow"),
    77: ("Schneegriesel", "snow"),
    80: ("Regenschauer", "rain"),
    81: ("Kräftige Regenschauer", "rain"),
    82: ("Starke Regenschauer", "rain"),
    85: ("Schneeschauer", "snow"),
    86: ("Starke Schneeschauer", "snow"),
    95: ("Gewitter", "storm"),
    96: ("Gewitter mit Hagel", "storm"),
    99: ("Starkes Gewitter mit Hagel", "storm"),
}

ICONS = {
    "sun": (
        '<svg viewBox="0 0 64 64" aria-hidden="true">'
        '<circle cx="32" cy="32" r="12" fill="black"/>'
        '<g stroke="black" stroke-width="4" stroke-linecap="round">'
        '<path d="M32 4v8M32 52v8M4 32h8M52 32h8M12.2 12.2l5.7 5.7m28.2 28.2 5.7 5.7'
        'M51.8 12.2l-5.7 5.7M17.9 46.1l-5.7 5.7"/></g></svg>'
    ),
    "cloud": (
        '<svg viewBox="0 0 64 64" aria-hidden="true">'
        '<path d="M17 47h32a11 11 0 0 0 1-22 18 18 0 0 0-34-3A13 13 0 0 0 17 47Z" '
        'fill="white" stroke="black" stroke-width="4" stroke-linejoin="round"/></svg>'
    ),
    "rain": (
        '<svg viewBox="0 0 64 64" aria-hidden="true">'
        '<path d="M15 36h34a10 10 0 0 0 1-20 17 17 0 0 0-32-3A12 12 0 0 0 15 36Z" '
        'fill="white" stroke="black" stroke-width="4" stroke-linejoin="round"/>'
        '<g stroke="black" stroke-width="4" stroke-linecap="round"><path d="m20 44-3 7m17-7-3 7m17-7-3 7"/></g>'
        '</svg>'
    ),
    "snow": (
        '<svg viewBox="0 0 64 64" aria-hidden="true">'
        '<path d="M15 34h34a10 10 0 0 0 1-20 17 17 0 0 0-32-3A12 12 0 0 0 15 34Z" '
        'fill="white" stroke="black" stroke-width="4" stroke-linejoin="round"/>'
        '<g fill="black"><circle cx="20" cy="47" r="3"/><circle cx="33" cy="52" r="3"/><circle cx="46" cy="45" r="3"/></g>'
        '</svg>'
    ),
    "fog": (
        '<svg viewBox="0 0 64 64" aria-hidden="true">'
        '<path d="M16 31h32a10 10 0 0 0 1-20 17 17 0 0 0-32-3A12 12 0 0 0 16 31Z" '
        'fill="white" stroke="black" stroke-width="4" stroke-linejoin="round"/>'
        '<g stroke="black" stroke-width="4" stroke-linecap="round"><path d="M9 41h46M14 51h36"/></g></svg>'
    ),
    "storm": (
        '<svg viewBox="0 0 64 64" aria-hidden="true">'
        '<path d="M15 34h34a10 10 0 0 0 1-20 17 17 0 0 0-32-3A12 12 0 0 0 15 34Z" '
        'fill="white" stroke="black" stroke-width="4" stroke-linejoin="round"/>'
        '<path d="m35 36-12 15h9l-3 11 15-18h-10l5-8Z" fill="black"/></svg>'
    ),
}


class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {"br", "div", "li", "p", "section", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag.lower() in self.BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)


def clean_text(value):
    parser = _TextExtractor()
    parser.feed(value or "")
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def truncate_teaser(text, limit=140):
    if len(text) <= limit:
        return text
    shortened = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if not shortened:
        shortened = text[: limit - 1]
    return shortened + "…"


def fetch_recent_news(label, url, now):
    request = Request(url, headers={"User-Agent": "Kindle-Dashboard/1.0"})
    try:
        with urlopen(request, timeout=15) as response:
            parsed = feedparser.parse(response.read())
    except Exception as error:
        print(f"RSS-Feed {label} nicht erreichbar ({url}): {error}", file=sys.stderr)
        return []

    if parsed.bozo:
        print(f"RSS-Feed {label} enthielt fehlerhaftes XML ({url}).", file=sys.stderr)

    cutoff = now - timedelta(days=1)
    news = []
    for entry in parsed.entries:
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        if not published:
            continue
        published_at = datetime.fromtimestamp(calendar.timegm(published), timezone.utc)
        if not cutoff <= published_at <= now:
            continue
        title = truncate_teaser(clean_text(entry.get("title", "")), 82)
        if not title:
            continue
        summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
        news.append(
            {
                "category": label,
                "title": title,
                "summary": truncate_teaser(summary),
                "published": published_at,
            }
        )
    news.sort(key=lambda item: item["published"], reverse=True)
    return news[:2]


def fetch_news():
    now = datetime.now(timezone.utc)
    news = []
    for label, url in RSS_FEEDS:
        news.extend(fetch_recent_news(label, url, now))

    munich_news = fetch_recent_news("MÜNCHEN", MUNICH_FEEDS[0], now)
    if not munich_news:
        munich_news = fetch_recent_news("MÜNCHEN", MUNICH_FEEDS[1], now)
    news.extend(munich_news)

    for label in ("WELT", "DEUTSCHLAND", "MÜNCHEN"):
        count = sum(item["category"] == label for item in news)
        for _ in range(2 - count):
            news.append(
                {
                    "category": label,
                    "title": "Keine Meldung der letzten 24 Stunden verfügbar",
                    "summary": "Der RSS-Feed lieferte derzeit keine passenden Meldungen.",
                }
            )
    return news


def fetch_weather():
    params = urlencode(
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": (
                "weather_code,temperature_2m_min,temperature_2m_max,"
                "precipitation_probability_max"
            ),
            "forecast_days": 7,
            "timezone": TIMEZONE,
        }
    )
    url = "https://api.open-meteo.com/v1/forecast?" + params
    with urlopen(url, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    daily = data["daily"]
    hourly = data["hourly"]
    today = daily["time"][0]
    today_date = datetime.strptime(today, "%Y-%m-%d")
    hourly_by_time = {time: index for index, time in enumerate(hourly["time"])}
    rain_segments = []
    for hour in range(6, 23):
        time = f"{today}T{hour:02d}:00"
        index = hourly_by_time.get(time)
        if index is None:
            raise ValueError(f"Open-Meteo did not return hourly data for {time}")
        rain = hourly["precipitation_probability"][index]
        if rain is None:
            raise ValueError(f"Open-Meteo did not return precipitation probability for {time}")
        if rain >= 60:
            rain_class = "rain-heavy"
        elif rain >= 20:
            rain_class = "rain-possible"
        else:
            rain_class = "rain-dry"
        rain_segments.append(
            {
                "start": f"{hour:02d}",
                "end": f"{hour + 1:02d}",
                "class": rain_class,
                "rain": rain,
            }
        )
    if len(rain_segments) != 17:
        raise ValueError(f"Open-Meteo returned {len(rain_segments)} rain segments; expected 17")

    timeline_ticks = []
    for hour in (6, 8, 11, 14, 17, 20, 23):
        timeline_ticks.append(
            {
                "time": f"{hour:02d}:00",
                "position": (hour - 6) / 17 * 100,
                "important": hour in (8, 17),
                "edge": "start" if hour == 6 else "end" if hour == 23 else "",
            }
        )

    weather_points = []
    for hour in (8, 12, 17, 21):
        time = f"{today}T{hour:02d}:00"
        index = hourly_by_time.get(time)
        if index is None:
            raise ValueError(f"Open-Meteo did not return hourly data for {time}")
        code = hourly["weather_code"][index]
        _, icon = WEATHER.get(code, ("Wetter", "cloud"))
        weather_points.append(
            {
                "time": f"{hour:02d}:00",
                "position": (hour - 6) / 17 * 100,
                "icon": ICONS[icon],
                "temperature": round(hourly["temperature_2m"][index]),
                "important": hour in (8, 17),
            }
        )

    forecast = []
    for index, date_text in enumerate(daily["time"]):
        forecast_date = datetime.strptime(date_text, "%Y-%m-%d")
        code = daily["weather_code"][index]
        description, icon = WEATHER.get(code, ("Wetter", "cloud"))
        forecast.append(
            {
                "weekday": WEEKDAYS[forecast_date.weekday()],
                "is_today": index == 0,
                "date": f"{forecast_date.day:02d}.{forecast_date.month:02d}.",
                "icon": ICONS[icon],
                "description": description,
                "min": round(daily["temperature_2m_min"][index]),
                "max": round(daily["temperature_2m_max"][index]),
                "rain": daily["precipitation_probability_max"][index],
            }
        )
    if len(forecast) != 7:
        raise ValueError(f"Open-Meteo returned {len(forecast)} forecast days; expected 7")

    return {
        "date": f"{today_date.day}. {MONTHS[today_date.month - 1]} {today_date.year}",
        "updated": "00:00",
        "temperature_min": round(daily["temperature_2m_min"][0]),
        "temperature_max": round(daily["temperature_2m_max"][0]),
        "condition": WEATHER.get(daily["weather_code"][0], ("Wetter", "cloud"))[0],
        "rain_segments": rain_segments,
        "timeline_ticks": timeline_ticks,
        "weather_points": weather_points,
        "forecast": forecast,
    }


def load_daily_term():
    with (ROOT / "begriffe.json").open(encoding="utf-8") as file:
        terms = json.load(file)
    if not terms:
        raise ValueError("begriffe.json enthält keine Einträge")
    return terms[date.today().toordinal() % len(terms)]


def main():
    weather = fetch_weather()
    term = load_daily_term()
    news = fetch_news()
    environment = Environment(
        loader=FileSystemLoader(str(ROOT / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
    )
    html = environment.get_template("dashboard.html").render(
        **weather,
        term=term,
        news=news,
    )
    html_path = ROOT / "dashboard-render.html"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=1,
        )
        page.set_content(html, wait_until="load")
        page.screenshot(path=str(html_path.with_suffix(".raw.png")))
        browser.close()

    raw_path = html_path.with_suffix(".raw.png")
    try:
        with Image.open(raw_path) as image:
            if image.size != (WIDTH, HEIGHT):
                raise ValueError(f"Rendered image has unexpected dimensions: {image.size}")
            grayscale = image.convert("L")
            if grayscale.mode != "L":
                raise ValueError(f"Expected grayscale mode L, got {grayscale.mode}")
            for name in ("screensaver.png", "screensaver-w.png"):
                grayscale.save(ROOT / name, format="PNG")
    finally:
        raw_path.unlink(missing_ok=True)
    print(f"Gespeichert: {ROOT / 'screensaver.png'} ({WIDTH}x{HEIGHT}, Graustufen L)")


if __name__ == "__main__":
    main()
