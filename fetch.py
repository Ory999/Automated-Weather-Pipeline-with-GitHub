import os
import sqlite3
import requests
from datetime import datetime, timedelta
from groq import Groq
from dotenv import load_dotenv

load_dotenv()


#Configuration

LOCATIONS = [
    {"name": "Hjørring",   "lat": 57.4637, "lon": 9.9801},
    {"name": "Copenhagen", "lat": 55.6761, "lon": 12.5683},
    {"name": "Aalborg",    "lat": 57.0488, "lon": 9.9217},
]

# Open-Meteo daily variable names
WEATHER_VARIABLES = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "windspeed_10m_max",
    "weathercode",
]

DB_PATH   = "weather.db"
HTML_DIR  = "docs"
HTML_PATH = os.path.join(HTML_DIR, "index.html")


# Database setup


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecasts (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            location          TEXT NOT NULL,
            forecast_date     TEXT NOT NULL,
            fetched_at        TEXT NOT NULL,
            temperature_max   REAL,
            temperature_min   REAL,
            precipitation_sum REAL,
            wind_speed_max    REAL,
            weathercode       INTEGER,
            UNIQUE(location, forecast_date)
        )
    """)
    conn.commit()


def upsert_forecast(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute("""
        INSERT INTO forecasts
            (location, forecast_date, fetched_at,
             temperature_max, temperature_min, precipitation_sum,
             wind_speed_max, weathercode)
        VALUES
            (:location, :forecast_date, :fetched_at,
             :temperature_max, :temperature_min, :precipitation_sum,
             :wind_speed_max, :weathercode)
        ON CONFLICT(location, forecast_date) DO UPDATE SET
            fetched_at        = excluded.fetched_at,
            temperature_max   = excluded.temperature_max,
            temperature_min   = excluded.temperature_min,
            precipitation_sum = excluded.precipitation_sum,
            wind_speed_max    = excluded.wind_speed_max,
            weathercode       = excluded.weathercode
    """, row)
    conn.commit()

# Fetch weather from Open-Meteo

# WMO weather interpretation codes
WMO_LABELS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Slight rain", 63: "Rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Snow", 75: "Heavy snow",
    80: "Slight showers", 81: "Showers", 82: "Heavy showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ heavy hail",
}

def wmo_label(code: int) -> str:
    return WMO_LABELS.get(code, f"Code {code}")


def fetch_weather(location: dict, target_date: str) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":      location["lat"],
        "longitude":     location["lon"],
        "daily":         ",".join(WEATHER_VARIABLES),
        "timezone":      "Europe/Copenhagen",
        "forecast_days": 2,   # today + tomorrow
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()

    daily = data["daily"]
    dates = daily["time"]
    idx   = dates.index(target_date)

    return {
        "location":          location["name"],
        "forecast_date":     target_date,
        "fetched_at":        datetime.utcnow().isoformat(timespec="seconds"),
        "temperature_max":   daily["temperature_2m_max"][idx],
        "temperature_min":   daily["temperature_2m_min"][idx],
        "precipitation_sum": daily["precipitation_sum"][idx],
        "wind_speed_max":    daily["windspeed_10m_max"][idx],
        "weathercode":       daily["weathercode"][idx],
    }

# Generate bilingual poem via Groq

def generate_poem(forecasts: list[dict]) -> str:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    weather_summary = "\n".join([
        f"- {f['location']}: max {f['temperature_max']}°C, min {f['temperature_min']}°C, "
        f"rain {f['precipitation_sum']} mm, wind {f['wind_speed_max']} km/h, "
        f"conditions: {wmo_label(f['weathercode'])}"
        for f in forecasts
    ])

    prompt = f"""You are a creative poet. Here is tomorrow's weather forecast for three locations in Denmark:

{weather_summary}

Write a short poem (3-4 stanzas) that:
1. Compares the weather across the three locations
2. Describes the differences vividly
3. Suggests where it would be nicest to be tomorrow
4. Is written in BOTH English AND Danish (English first, then Danish translation)

Separate the two language versions with a line containing only three dashes: ---
Keep the tone warm and poetic, not clinical."""

    chat = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.85,
        max_tokens=600,
    )
    return chat.choices[0].message.content.strip()


# Build GitHub Pages HTML

def build_html(forecasts: list[dict], poem: str, target_date: str) -> str:
    rows = ""
    for f in forecasts:
        rows += f"""
        <tr>
            <td>{f['location']}</td>
            <td>{f['temperature_max']}°C / {f['temperature_min']}°C</td>
            <td>{f['precipitation_sum']} mm</td>
            <td>{f['wind_speed_max']} km/h</td>
            <td>{wmo_label(f['weathercode'])}</td>
        </tr>"""

    # Split poem into English / Danish halves on the --- separator
    parts        = poem.split("---")
    english_poem = parts[0].strip() if len(parts) >= 1 else poem
    danish_poem  = parts[1].strip() if len(parts) >= 2 else ""

    def poem_to_html(text: str) -> str:
        html_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            html_lines.append('<br>' if not stripped else f'<p>{stripped}</p>')
        return "\n".join(html_lines)

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Weather Poem - {target_date}</title>
  <style>
    body {{
      font-family: Georgia, serif;
      max-width: 800px;
      margin: 40px auto;
      padding: 0 20px;
      background: #f9f6f0;
      color: #2c2c2c;
    }}
    h1 {{ font-size: 1.8rem; margin-bottom: 4px; }}
    .subtitle {{ color: #888; font-size: 0.9rem; margin-bottom: 32px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 40px;
      font-family: monospace;
      font-size: 0.9rem;
    }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th {{ background: #eee; }}
    .poem-section {{ margin-bottom: 40px; }}
    .poem-section h2 {{ font-size: 1.1rem; letter-spacing: 0.05em; color: #555; }}
    .poem-section p {{ line-height: 1.8; margin: 0 0 2px 0; }}
    footer {{ font-size: 0.75rem; color: #aaa; margin-top: 60px; }}
  </style>
</head>
<body>
  <h1>Weather Poem</h1>
  <p class="subtitle">Forecast for {target_date} - auto-generated on {now}</p>

  <h2>Tomorrow's Forecast</h2>
  <table>
    <thead>
      <tr>
        <th>Location</th>
        <th>Temp (max/min)</th>
        <th>Precipitation</th>
        <th>Wind Speed</th>
        <th>Conditions</th>
      </tr>
    </thead>
    <tbody>{rows}
    </tbody>
  </table>

  <div class="poem-section">
    <h2>English</h2>
    {poem_to_html(english_poem)}
  </div>

  <div class="poem-section">
    <h2>Dansk</h2>
    {poem_to_html(danish_poem)}
  </div>

  <footer>Pipeline powered by Open-Meteo · Groq · GitHub Actions</footer>
</body>
</html>"""

# Main

def main():
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Target date: {tomorrow}")

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    forecasts = []
    for loc in LOCATIONS:
        print(f"Fetching weather for {loc['name']}...")
        forecast = fetch_weather(loc, tomorrow)
        upsert_forecast(conn, forecast)
        forecasts.append(forecast)
        print(f"  -> {forecast['temperature_max']}C max | "
              f"{forecast['precipitation_sum']} mm rain | "
              f"{wmo_label(forecast['weathercode'])}")

    conn.close()

    print("Generating poem via Groq...")
    poem = generate_poem(forecasts)
    print("\n--- POEM PREVIEW ---")
    print(poem)
    print("--------------------\n")

    os.makedirs(HTML_DIR, exist_ok=True)
    html = build_html(forecasts, poem, tomorrow)
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML written to {HTML_PATH}")
    print("Pipeline complete.")


if __name__ == "__main__":
    main()
