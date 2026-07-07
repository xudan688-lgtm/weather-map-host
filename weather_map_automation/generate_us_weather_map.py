#!/usr/bin/env python3
"""
Generate a daily 50-state US weather map in Chinese.

Data sources:
- Weather: Open-Meteo Forecast API, no API key required.
- State geometry: PublicaMundi US states GeoJSON, cached locally after first use.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import math
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 fallback.
    ZoneInfo = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - runtime guard.
    raise SystemExit(
        "Pillow is required. Run this with the bundled Codex Python runtime."
    ) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = WORKSPACE_DIR / "daily_us_weather_maps"
GEOJSON_PATH = SCRIPT_DIR / "us-states.geojson"
DINGTALK_CONFIG_PATH = SCRIPT_DIR / "dingtalk_config.json"
GITHUB_PAGES_CONFIG_PATH = SCRIPT_DIR / "github_pages_config.json"
GEOJSON_URL = (
    "https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/"
    "data/geojson/us-states.json"
)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
LOCAL_TZ = "Asia/Shanghai"

CANVAS_W = 2400
CANVAS_H = 1600

COLORS = {
    "navy": (10, 27, 72),
    "text": (24, 29, 41),
    "muted": (92, 101, 116),
    "border": (28, 64, 112),
    "panel_border": (195, 204, 218),
    "background": (248, 249, 251),
    "map_bg": (243, 245, 248),
    "state_outline": (255, 255, 255),
    "coast_outline": (190, 196, 205),
    "extreme": (244, 69, 69),
    "hot": (255, 166, 58),
    "mild": (226, 228, 232),
    "cool": (91, 161, 232),
    "missing": (206, 211, 219),
    "sun": (255, 185, 35),
    "cloud": (250, 253, 255),
    "rain": (42, 126, 198),
    "storm": (47, 74, 128),
}


STATE_CITIES = [
    ("AL", "Alabama", "亚拉巴马", "Birmingham", 33.5186, -86.8104),
    ("AK", "Alaska", "阿拉斯加", "Anchorage", 61.2181, -149.9003),
    ("AZ", "Arizona", "亚利桑那", "Phoenix", 33.4484, -112.0740),
    ("AR", "Arkansas", "阿肯色", "Little Rock", 34.7465, -92.2896),
    ("CA", "California", "加利福尼亚", "Los Angeles", 34.0522, -118.2437),
    ("CO", "Colorado", "科罗拉多", "Denver", 39.7392, -104.9903),
    ("CT", "Connecticut", "康涅狄格", "Bridgeport", 41.1792, -73.1894),
    ("DE", "Delaware", "特拉华", "Wilmington", 39.7391, -75.5398),
    ("FL", "Florida", "佛罗里达", "Miami", 25.7617, -80.1918),
    ("GA", "Georgia", "佐治亚", "Atlanta", 33.7490, -84.3880),
    ("HI", "Hawaii", "夏威夷", "Honolulu", 21.3069, -157.8583),
    ("ID", "Idaho", "爱达荷", "Boise", 43.6150, -116.2023),
    ("IL", "Illinois", "伊利诺伊", "Chicago", 41.8781, -87.6298),
    ("IN", "Indiana", "印第安纳", "Indianapolis", 39.7684, -86.1581),
    ("IA", "Iowa", "艾奥瓦", "Des Moines", 41.5868, -93.6250),
    ("KS", "Kansas", "堪萨斯", "Wichita", 37.6872, -97.3301),
    ("KY", "Kentucky", "肯塔基", "Louisville", 38.2527, -85.7585),
    ("LA", "Louisiana", "路易斯安那", "New Orleans", 29.9511, -90.0715),
    ("ME", "Maine", "缅因", "Portland", 43.6591, -70.2568),
    ("MD", "Maryland", "马里兰", "Baltimore", 39.2904, -76.6122),
    ("MA", "Massachusetts", "马萨诸塞", "Boston", 42.3601, -71.0589),
    ("MI", "Michigan", "密歇根", "Detroit", 42.3314, -83.0458),
    ("MN", "Minnesota", "明尼苏达", "Minneapolis", 44.9778, -93.2650),
    ("MS", "Mississippi", "密西西比", "Jackson", 32.2988, -90.1848),
    ("MO", "Missouri", "密苏里", "Kansas City", 39.0997, -94.5786),
    ("MT", "Montana", "蒙大拿", "Billings", 45.7833, -108.5007),
    ("NE", "Nebraska", "内布拉斯加", "Omaha", 41.2565, -95.9345),
    ("NV", "Nevada", "内华达", "Las Vegas", 36.1699, -115.1398),
    ("NH", "New Hampshire", "新罕布什尔", "Manchester", 42.9956, -71.4548),
    ("NJ", "New Jersey", "新泽西", "Newark", 40.7357, -74.1724),
    ("NM", "New Mexico", "新墨西哥", "Albuquerque", 35.0844, -106.6504),
    ("NY", "New York", "纽约", "New York City", 40.7128, -74.0060),
    ("NC", "North Carolina", "北卡罗来纳", "Charlotte", 35.2271, -80.8431),
    ("ND", "North Dakota", "北达科他", "Fargo", 46.8772, -96.7898),
    ("OH", "Ohio", "俄亥俄", "Columbus", 39.9612, -82.9988),
    ("OK", "Oklahoma", "俄克拉何马", "Oklahoma City", 35.4676, -97.5164),
    ("OR", "Oregon", "俄勒冈", "Portland", 45.5152, -122.6784),
    ("PA", "Pennsylvania", "宾夕法尼亚", "Philadelphia", 39.9526, -75.1652),
    ("RI", "Rhode Island", "罗德岛", "Providence", 41.8240, -71.4128),
    ("SC", "South Carolina", "南卡罗来纳", "Charleston", 32.7765, -79.9311),
    ("SD", "South Dakota", "南达科他", "Sioux Falls", 43.5446, -96.7311),
    ("TN", "Tennessee", "田纳西", "Nashville", 36.1627, -86.7816),
    ("TX", "Texas", "德克萨斯", "Houston", 29.7604, -95.3698),
    ("UT", "Utah", "犹他", "Salt Lake City", 40.7608, -111.8910),
    ("VT", "Vermont", "佛蒙特", "Burlington", 44.4759, -73.2121),
    ("VA", "Virginia", "弗吉尼亚", "Virginia Beach", 36.8529, -75.9780),
    ("WA", "Washington", "华盛顿", "Seattle", 47.6062, -122.3321),
    ("WV", "West Virginia", "西弗吉尼亚", "Charleston", 38.3498, -81.6326),
    ("WI", "Wisconsin", "威斯康星", "Milwaukee", 43.0389, -87.9065),
    ("WY", "Wyoming", "怀俄明", "Cheyenne", 41.1400, -104.8202),
]

STATE_BY_NAME = {
    state: {
        "abbr": abbr,
        "state": state,
        "state_zh": state_zh,
        "city": city,
        "lat": lat,
        "lon": lon,
    }
    for abbr, state, state_zh, city, lat, lon in STATE_CITIES
}
STATE_BY_ABBR = {item["abbr"]: item for item in STATE_BY_NAME.values()}
STATE_NAMES_50 = set(STATE_BY_NAME)
LOWER_48 = STATE_NAMES_50 - {"Alaska", "Hawaii"}

CALLOUTS = {
    "VT": (1740, 230),
    "NH": (1740, 330),
    "MA": (1740, 430),
    "RI": (1740, 530),
    "CT": (1740, 630),
    "NJ": (1740, 730),
    "DE": (1740, 830),
    "MD": (1740, 930),
}

LABEL_OFFSETS = {
    "WA": (-30, -55),
    "OR": (-45, 15),
    "CA": (-42, 35),
    "ID": (15, -45),
    "NV": (0, -30),
    "MT": (0, -38),
    "WY": (0, 25),
    "UT": (0, 30),
    "AZ": (-5, 40),
    "CO": (0, 35),
    "NM": (0, 42),
    "ND": (5, -35),
    "SD": (5, 25),
    "NE": (5, 25),
    "KS": (0, 28),
    "OK": (5, 28),
    "TX": (-55, 55),
    "MN": (0, -38),
    "IA": (0, 24),
    "MO": (5, 32),
    "AR": (0, 30),
    "LA": (0, 35),
    "WI": (20, -20),
    "IL": (-25, 35),
    "MS": (-25, 32),
    "MI": (45, 5),
    "IN": (35, 28),
    "OH": (45, 22),
    "KY": (15, 28),
    "TN": (20, 35),
    "AL": (20, 32),
    "GA": (25, 35),
    "FL": (30, 50),
    "SC": (30, 38),
    "NC": (45, 28),
    "VA": (55, 20),
    "WV": (45, 30),
    "PA": (40, 18),
    "NY": (-20, 25),
    "ME": (-20, 30),
}


def local_today() -> str:
    if ZoneInfo is None:
        return datetime.now().date().isoformat()
    return datetime.now(ZoneInfo(LOCAL_TZ)).date().isoformat()


def load_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


FONTS = {size: load_font(size) for size in [15, 16, 18, 20, 22, 24, 26, 28, 30, 32, 36, 42, 44, 54, 64, 72]}


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_centered(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    y: float,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int] | None = None,
) -> None:
    w, _ = text_size(draw, text, font)
    draw.text(
        (center_x - w / 2, y),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            if current:
                lines.append(current)
                current = ""
            continue
        trial = current + char
        if current and text_size(draw, trial, font)[0] > max_width:
            lines.append(current)
            current = char
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def request_json(url: str) -> dict | list:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "daily-us-weather-map/1.0 (local automation)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_geojson(refresh: bool = False) -> dict:
    if refresh or not GEOJSON_PATH.exists():
        req = urllib.request.Request(
            GEOJSON_URL,
            headers={"User-Agent": "daily-us-weather-map/1.0"},
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            payload = response.read()
        data = json.loads(payload.decode("utf-8"))
        GEOJSON_PATH.write_bytes(payload)
        return data
    with GEOJSON_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fetch_weather(date_str: str) -> list[dict]:
    latitudes = ",".join(f"{item['lat']:.4f}" for item in STATE_BY_NAME.values())
    longitudes = ",".join(f"{item['lon']:.4f}" for item in STATE_BY_NAME.values())
    params = urllib.parse.urlencode(
        {
            "latitude": latitudes,
            "longitude": longitudes,
            "daily": ",".join(
                [
                    "weather_code",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_sum",
                    "rain_sum",
                    "showers_sum",
                    "snowfall_sum",
                    "wind_speed_10m_max",
                ]
            ),
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "timezone": "auto",
            "start_date": date_str,
            "end_date": date_str,
        }
    )
    payload = request_json(f"{OPEN_METEO_URL}?{params}")
    if isinstance(payload, dict):
        payload = [payload]
    records: list[dict] = []
    for base, weather_item in zip(STATE_BY_NAME.values(), payload):
        daily = weather_item.get("daily", {})
        temp_max_values = daily.get("temperature_2m_max") or []
        temp_min_values = daily.get("temperature_2m_min") or []
        code_values = daily.get("weather_code") or []
        precip_values = daily.get("precipitation_sum") or []
        rain_values = daily.get("rain_sum") or []
        showers_values = daily.get("showers_sum") or []
        snow_values = daily.get("snowfall_sum") or []
        wind_values = daily.get("wind_speed_10m_max") or []
        date_values = daily.get("time") or []
        temp = temp_max_values[0] if temp_max_values else None
        temp_min = temp_min_values[0] if temp_min_values else None
        code = code_values[0] if code_values else None
        record = dict(base)
        record.update(
            {
                "temperature_c": None if temp is None else round(float(temp)),
                "temperature_raw_c": temp,
                "temperature_max_c": None if temp is None else round(float(temp)),
                "temperature_min_c": None if temp_min is None else round(float(temp_min)),
                "weather_code": code,
                "cloud_cover": None,
                "precipitation_mm": precip_values[0] if precip_values else None,
                "rain_mm": rain_values[0] if rain_values else None,
                "showers_mm": showers_values[0] if showers_values else None,
                "snowfall_cm": snow_values[0] if snow_values else None,
                "wind_speed_kmh": wind_values[0] if wind_values else None,
                "weather_time": date_values[0] if date_values else date_str,
                "timezone": weather_item.get("timezone"),
                "condition_zh": condition_zh(code, None),
            }
        )
        records.append(record)
    if len(records) != 50:
        raise RuntimeError(f"Expected 50 weather records, got {len(records)}")
    return records


def latest_cached_weather(output_dir: Path) -> tuple[list[dict], str] | None:
    files = sorted(output_dir.glob("weather_data_*.json"))
    for path in reversed(files):
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            records = payload.get("records")
            if isinstance(records, list) and len(records) == 50:
                return records, payload.get("date", path.stem.replace("weather_data_", ""))
        except (OSError, json.JSONDecodeError):
            continue
    return None


def condition_zh(code: int | None, cloud_cover: int | float | None) -> str:
    if code is None:
        return "未知"
    code = int(code)
    cloud = 0 if cloud_cover is None else float(cloud_cover)
    if code == 0:
        return "晴"
    if code == 1:
        return "大部晴"
    if code == 2:
        return "部分晴"
    if code == 3:
        return "多云" if cloud >= 70 else "大部分多云"
    if code in {45, 48}:
        return "雾"
    if code in {51, 53, 55, 56, 57}:
        return "毛毛雨"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "雨"
    if code in {71, 73, 75, 77, 85, 86}:
        return "雪"
    if code in {95, 96, 99}:
        return "雷雨"
    return "多云"


def temp_category(temp: int | None) -> str:
    if temp is None:
        return "missing"
    if temp >= 40:
        return "extreme"
    if temp >= 30:
        return "hot"
    if temp >= 20:
        return "mild"
    return "cool"


def iter_polygons(geometry: dict) -> list[list[list[list[float]]]]:
    if geometry.get("type") == "Polygon":
        return [geometry.get("coordinates", [])]
    if geometry.get("type") == "MultiPolygon":
        return [polygon for polygon in geometry.get("coordinates", [])]
    return []


def all_lon_lats(features: list[dict]):
    for feature in features:
        for polygon in iter_polygons(feature.get("geometry", {})):
            for ring in polygon:
                for point in ring:
                    yield float(point[0]), float(point[1])


def albers_lower_48(lon: float, lat: float) -> tuple[float, float]:
    phi = math.radians(lat)
    lam = math.radians(lon)
    phi0 = math.radians(23.0)
    phi1 = math.radians(29.5)
    phi2 = math.radians(45.5)
    lam0 = math.radians(-96.0)
    n = 0.5 * (math.sin(phi1) + math.sin(phi2))
    c = math.cos(phi1) ** 2 + 2 * n * math.sin(phi1)
    rho = math.sqrt(max(0, c - 2 * n * math.sin(phi))) / n
    rho0 = math.sqrt(max(0, c - 2 * n * math.sin(phi0))) / n
    theta = n * (lam - lam0)
    return rho * math.sin(theta), rho0 - rho * math.cos(theta)


def lon_lat_raw(lon: float, lat: float) -> tuple[float, float]:
    return lon, lat


def make_transform(
    features: list[dict],
    raw_project,
    box: tuple[int, int, int, int],
    padding: int = 12,
) -> callable:
    raw_points = [raw_project(lon, lat) for lon, lat in all_lon_lats(features)]
    min_x = min(point[0] for point in raw_points)
    max_x = max(point[0] for point in raw_points)
    min_y = min(point[1] for point in raw_points)
    max_y = max(point[1] for point in raw_points)
    x0, y0, x1, y1 = box
    width = x1 - x0 - 2 * padding
    height = y1 - y0 - 2 * padding
    scale = min(width / (max_x - min_x), height / (max_y - min_y))
    used_w = (max_x - min_x) * scale
    used_h = (max_y - min_y) * scale
    ox = x0 + padding + (width - used_w) / 2
    oy = y0 + padding + (height - used_h) / 2

    def transform(lon: float, lat: float) -> tuple[float, float]:
        raw_x, raw_y = raw_project(lon, lat)
        x = ox + (raw_x - min_x) * scale
        y = oy + (max_y - raw_y) * scale
        return x, y

    return transform


def draw_state_polygons(
    draw: ImageDraw.ImageDraw,
    features: list[dict],
    project,
    records_by_state: dict[str, dict],
    hole_fill: tuple[int, int, int],
) -> None:
    for feature in features:
        state_name = feature.get("properties", {}).get("name")
        record = records_by_state.get(state_name)
        fill = COLORS[temp_category(record.get("temperature_c") if record else None)]
        for polygon in iter_polygons(feature.get("geometry", {})):
            if not polygon:
                continue
            outer = [project(float(p[0]), float(p[1])) for p in polygon[0]]
            if len(outer) >= 3:
                draw.polygon(outer, fill=fill)
            for hole in polygon[1:]:
                points = [project(float(p[0]), float(p[1])) for p in hole]
                if len(points) >= 3:
                    draw.polygon(points, fill=hole_fill)
    for feature in features:
        for polygon in iter_polygons(feature.get("geometry", {})):
            for ring_index, ring in enumerate(polygon):
                points = [project(float(p[0]), float(p[1])) for p in ring]
                if len(points) >= 2:
                    color = COLORS["state_outline"] if ring_index == 0 else COLORS["coast_outline"]
                    width = 3 if ring_index == 0 else 1
                    draw.line(points + [points[0]], fill=color, width=width, joint="curve")


def draw_weather_icon(
    draw: ImageDraw.ImageDraw,
    code: int | None,
    cloud_cover: int | float | None,
    x: float,
    y: float,
    size: int = 36,
) -> None:
    code = 3 if code is None else int(code)
    if code == 0:
        draw_sun(draw, x + size / 2, y + size / 2, size * 0.22)
    elif code in {1, 2}:
        draw_sun(draw, x + size * 0.42, y + size * 0.38, size * 0.18)
        draw_cloud(draw, x + size * 0.50, y + size * 0.60, size * 0.55)
    elif code in {61, 63, 65, 66, 67, 80, 81, 82, 51, 53, 55, 56, 57}:
        draw_cloud(draw, x + size * 0.50, y + size * 0.44, size * 0.62)
        draw_rain(draw, x + size * 0.32, y + size * 0.62, size)
    elif code in {71, 73, 75, 77, 85, 86}:
        draw_cloud(draw, x + size * 0.50, y + size * 0.44, size * 0.62)
        draw_snow(draw, x + size * 0.28, y + size * 0.63, size)
    elif code in {95, 96, 99}:
        draw_cloud(draw, x + size * 0.50, y + size * 0.40, size * 0.65, fill=COLORS["storm"])
        draw_lightning(draw, x + size * 0.50, y + size * 0.58, size)
    else:
        cloud = 0 if cloud_cover is None else float(cloud_cover)
        if cloud < 60:
            draw_sun(draw, x + size * 0.40, y + size * 0.36, size * 0.16)
            draw_cloud(draw, x + size * 0.52, y + size * 0.58, size * 0.58)
        else:
            draw_cloud(draw, x + size * 0.50, y + size * 0.52, size * 0.70)


def draw_sun(draw: ImageDraw.ImageDraw, cx: float, cy: float, radius: float) -> None:
    for angle in range(0, 360, 45):
        rad = math.radians(angle)
        x1 = cx + math.cos(rad) * radius * 1.45
        y1 = cy + math.sin(rad) * radius * 1.45
        x2 = cx + math.cos(rad) * radius * 2.05
        y2 = cy + math.sin(rad) * radius * 2.05
        draw.line((x1, y1, x2, y2), fill=(148, 93, 0), width=max(1, int(radius / 4)))
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=COLORS["sun"],
        outline=(148, 93, 0),
        width=max(1, int(radius / 5)),
    )


def draw_cloud(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    scale: float,
    fill: tuple[int, int, int] | None = None,
) -> None:
    fill = COLORS["cloud"] if fill is None else fill
    outline = (57, 67, 84)
    w = scale
    h = scale * 0.42
    draw.ellipse((cx - w * 0.45, cy - h * 0.25, cx - w * 0.07, cy + h * 0.45), fill=fill, outline=outline, width=2)
    draw.ellipse((cx - w * 0.20, cy - h * 0.55, cx + w * 0.22, cy + h * 0.32), fill=fill, outline=outline, width=2)
    draw.ellipse((cx + w * 0.02, cy - h * 0.18, cx + w * 0.47, cy + h * 0.47), fill=fill, outline=outline, width=2)
    draw.rounded_rectangle((cx - w * 0.48, cy, cx + w * 0.52, cy + h * 0.50), radius=int(h * 0.22), fill=fill, outline=outline, width=2)


def draw_rain(draw: ImageDraw.ImageDraw, x: float, y: float, size: int) -> None:
    for i in range(3):
        dx = x + i * size * 0.17
        draw.line((dx, y, dx - size * 0.04, y + size * 0.16), fill=COLORS["rain"], width=max(2, size // 14))


def draw_snow(draw: ImageDraw.ImageDraw, x: float, y: float, size: int) -> None:
    for i in range(3):
        cx = x + i * size * 0.18
        cy = y + (i % 2) * size * 0.04
        r = size * 0.045
        draw.line((cx - r, cy, cx + r, cy), fill=COLORS["rain"], width=2)
        draw.line((cx, cy - r, cx, cy + r), fill=COLORS["rain"], width=2)


def draw_lightning(draw: ImageDraw.ImageDraw, x: float, y: float, size: int) -> None:
    points = [
        (x - size * 0.03, y),
        (x + size * 0.11, y),
        (x + size * 0.01, y + size * 0.18),
        (x + size * 0.16, y + size * 0.18),
        (x - size * 0.08, y + size * 0.48),
        (x - size * 0.02, y + size * 0.24),
        (x - size * 0.16, y + size * 0.24),
    ]
    draw.polygon(points, fill=(255, 203, 42), outline=(115, 74, 0))


def draw_city_label(
    draw: ImageDraw.ImageDraw,
    record: dict,
    x: float,
    y: float,
    compact: bool = False,
) -> None:
    city_font = FONTS[18 if compact else 20]
    temp_font = FONTS[32 if compact else 36]
    cond_font = FONTS[16 if compact else 18]
    stroke = (255, 255, 255)
    fill = COLORS["text"]
    city = record["city"]
    temp = "--" if record.get("temperature_c") is None else f"{record['temperature_c']}°"
    cond = record.get("condition_zh", "未知")
    draw_centered(draw, x, y, city, city_font, fill, 2, stroke)
    draw_centered(draw, x, y + (20 if compact else 24), temp, temp_font, fill, 3, stroke)
    icon_size = 24 if compact else 28
    cond_w, _ = text_size(draw, cond, cond_font)
    start_x = x - (icon_size + 6 + cond_w) / 2
    draw_weather_icon(draw, record.get("weather_code"), record.get("cloud_cover"), start_x, y + (60 if compact else 68), icon_size)
    draw.text(
        (start_x + icon_size + 6, y + (63 if compact else 72)),
        cond,
        font=cond_font,
        fill=fill,
        stroke_width=2,
        stroke_fill=stroke,
    )


def draw_callout(
    draw: ImageDraw.ImageDraw,
    record: dict,
    source_xy: tuple[float, float],
    box_xy: tuple[int, int],
) -> None:
    x, y = box_xy
    w, h = 158, 82
    line_end = (x, y + h / 2)
    draw.line((source_xy[0], source_xy[1], line_end[0], line_end[1]), fill=COLORS["border"], width=2)
    draw.rounded_rectangle(
        (x, y, x + w, y + h),
        radius=8,
        fill=(255, 255, 255),
        outline=COLORS["border"],
        width=2,
    )
    temp = "--" if record.get("temperature_c") is None else f"{record['temperature_c']}°"
    draw.text((x + 12, y + 10), f"{record['abbr']} {record['city']}", font=FONTS[16], fill=COLORS["text"])
    draw.text((x + 12, y + 32), temp, font=FONTS[28], fill=COLORS["text"])
    draw_weather_icon(draw, record.get("weather_code"), record.get("cloud_cover"), x + 74, y + 34, 28)
    draw.text((x + 12, y + 62), record.get("condition_zh", "未知"), font=FONTS[16], fill=COLORS["text"])


def draw_panel_header(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    number: str,
    title: str,
    accent: tuple[int, int, int],
) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle((x0, y0, x1, y1), radius=14, fill=(255, 255, 255), outline=accent, width=3)
    draw.ellipse((x0 + 18, y0 + 22, x0 + 78, y0 + 82), fill=accent, outline=accent)
    draw_centered(draw, x0 + 48, y0 + 29, number, FONTS[36], (255, 255, 255))
    draw.rounded_rectangle((x0 + 88, y0 + 30, x1 - 22, y0 + 76), radius=8, fill=accent)
    draw.text((x0 + 112, y0 + 39), title, font=FONTS[26], fill=(255, 255, 255))


def draw_temperature_panels(draw: ImageDraw.ImageDraw, records: list[dict]) -> None:
    x0, w = 1940, 420
    extreme_box = (x0, 170, x0 + w, 440)
    hot_box = (x0, 462, x0 + w, 1182)
    cool_box = (x0, 1202, x0 + w, 1418)

    draw_panel_header(draw, extreme_box, "1", "极端高温区域", (221, 35, 31))
    extreme = sorted(
        [r for r in records if r.get("temperature_c") is not None and r["temperature_c"] >= 40],
        key=lambda r: r["temperature_c"],
        reverse=True,
    )
    y = extreme_box[1] + 112
    if not extreme:
        draw.text((x0 + 32, y), "今日暂无 ≥40°C 城市", font=FONTS[22], fill=COLORS["muted"])
    for record in extreme[:4]:
        draw.ellipse((x0 + 28, y + 10, x0 + 40, y + 22), fill=(221, 35, 31))
        draw.text((x0 + 52, y), f"{record['state_zh']}  {record['city']}", font=FONTS[22], fill=COLORS["text"])
        temp = f"{record['temperature_c']}°C"
        tw, _ = text_size(draw, temp, FONTS[28])
        draw.text((x0 + w - 34 - tw, y - 4), temp, font=FONTS[28], fill=(221, 35, 31))
        y += 48

    draw_panel_header(draw, hot_box, "2", "高温炎热重点区域", (232, 100, 0))
    hot = sorted(
        [r for r in records if r.get("temperature_c") is not None and 30 <= r["temperature_c"] < 40],
        key=lambda r: r["temperature_c"],
        reverse=True,
    )
    y = hot_box[1] + 108
    for record in hot[:13]:
        draw.ellipse((x0 + 30, y + 10, x0 + 39, y + 19), fill=(232, 100, 0))
        draw.text((x0 + 52, y - 2), f"{record['state_zh']}  {record['city']}", font=FONTS[20], fill=COLORS["text"])
        temp = f"{record['temperature_c']}°C"
        tw, _ = text_size(draw, temp, FONTS[22])
        draw.text((x0 + w - 36 - tw, y - 4), temp, font=FONTS[22], fill=(232, 100, 0))
        y += 43
    if not hot:
        draw.text((x0 + 32, y), "今日暂无 30-39°C 城市", font=FONTS[22], fill=COLORS["muted"])

    draw_panel_header(draw, cool_box, "3", "低温偏凉 / 降雨较集中", (23, 96, 184))
    cool = [r for r in records if r.get("temperature_c") is not None and r["temperature_c"] <= 19]
    rainy_codes = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
    rainy = [r for r in records if int(r.get("weather_code") or 0) in rainy_codes]
    cool_names = "、".join(r["state_zh"] for r in sorted(cool, key=lambda r: r["temperature_c"])[:5]) or "暂无明显偏凉州"
    rain_names = "、".join(r["state_zh"] for r in rainy[:6]) or "暂无明显降雨/雷雨集中区"
    summary = f"偏凉：{cool_names}。降雨/雷雨：{rain_names}。"
    yy = cool_box[1] + 98
    for line in wrap_text(draw, summary, FONTS[20], w - 54)[:3]:
        draw.text((x0 + 28, yy), line, font=FONTS[20], fill=COLORS["text"])
        yy += 32


def draw_legends(draw: ImageDraw.ImageDraw) -> None:
    x0, y0, x1, y1 = 24, 1430, 2376, 1572
    draw.rounded_rectangle((x0, y0, x1, y1), radius=14, fill=(255, 255, 255), outline=COLORS["border"], width=2)
    draw.text((322, y0 + 18), "温度图例（摄氏度）", font=FONTS[24], fill=COLORS["text"])
    items = [
        (COLORS["extreme"], "极端高温\n(≥40°C)"),
        (COLORS["hot"], "高温炎热\n(30-39°C)"),
        (COLORS["mild"], "温和舒适\n(20-29°C)"),
        (COLORS["cool"], "低温偏凉\n(≤19°C)"),
    ]
    x = 66
    for color, label in items:
        draw.rounded_rectangle((x, y0 + 72, x + 60, y0 + 132), radius=5, fill=color)
        for idx, line in enumerate(label.split("\n")):
            draw.text((x + 76, y0 + 71 + idx * 28), line, font=FONTS[18], fill=COLORS["text"])
        x += 210

    divider_x = 880
    draw.line((divider_x, y0 + 18, divider_x, y1 - 18), fill=COLORS["border"], width=2)
    draw.text((1490, y0 + 18), "天气图例", font=FONTS[24], fill=COLORS["text"])
    weather_items = [
        (0, "晴"),
        (1, "大部晴"),
        (2, "部分晴"),
        (3, "多云"),
        (61, "雨"),
        (95, "雷雨"),
        (71, "雪"),
    ]
    wx = 960
    for code, label in weather_items:
        draw_weather_icon(draw, code, 80, wx, y0 + 66, 42)
        tw, _ = text_size(draw, label, FONTS[18])
        draw.text((wx + 21 - tw / 2, y0 + 115), label, font=FONTS[18], fill=COLORS["text"])
        wx += 180


def draw_inset_box(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str) -> None:
    draw.rounded_rectangle(box, radius=10, fill=(255, 255, 255), outline=(115, 143, 180), width=2)
    x0, y0, _, _ = box
    draw.text((x0 + 14, y0 + 12), title, font=FONTS[18], fill=COLORS["border"])


def render_map(records: list[dict], geojson: dict, date_str: str, output_path: Path, data_note: str = "") -> None:
    image = Image.new("RGB", (CANVAS_W, CANVAS_H), COLORS["background"])
    draw = ImageDraw.Draw(image)
    records_by_state = {record["state"]: record for record in records}
    records_by_abbr = {record["abbr"]: record for record in records}

    draw.rounded_rectangle((1, 1, CANVAS_W - 2, CANVAS_H - 2), radius=10, outline=COLORS["border"], width=2)
    draw_centered(draw, CANVAS_W / 2 - 150, 26, "美国50州天气地图（摄氏度）", FONTS[72], COLORS["navy"])
    subtitle = f"数据日期：{date_str}  |  每州选 1 个代表性主要城市  |  温度为今日最高温"
    draw_centered(draw, CANVAS_W / 2 - 150, 116, subtitle, FONTS[28], COLORS["text"])
    if data_note:
        draw_centered(draw, CANVAS_W / 2 - 150, 150, data_note, FONTS[18], (189, 72, 25))

    features = [
        feature
        for feature in geojson.get("features", [])
        if feature.get("properties", {}).get("name") in STATE_NAMES_50
    ]
    feature_by_name = {feature.get("properties", {}).get("name"): feature for feature in features}
    lower_features = [feature_by_name[name] for name in LOWER_48 if name in feature_by_name]
    alaska_features = [feature_by_name["Alaska"]]
    hawaii_features = [feature_by_name["Hawaii"]]

    map_box = (38, 168, 1905, 1390)
    lower_box = (55, 178, 1710, 1198)
    draw.rounded_rectangle(map_box, radius=16, fill=COLORS["map_bg"], outline=(215, 221, 230), width=1)
    lower_project = make_transform(lower_features, albers_lower_48, lower_box, padding=14)
    draw_state_polygons(draw, lower_features, lower_project, records_by_state, COLORS["map_bg"])

    # Insets keep Alaska and Hawaii legible without distorting the lower-48 map.
    alaska_box = (62, 1135, 365, 1370)
    hawaii_box = (390, 1218, 675, 1370)
    draw_inset_box(draw, alaska_box, "Alaska")
    draw_inset_box(draw, hawaii_box, "Hawaii")
    alaska_project = make_transform(alaska_features, lon_lat_raw, alaska_box, padding=28)
    hawaii_project = make_transform(hawaii_features, lon_lat_raw, hawaii_box, padding=28)
    draw_state_polygons(draw, alaska_features, alaska_project, records_by_state, (255, 255, 255))
    draw_state_polygons(draw, hawaii_features, hawaii_project, records_by_state, (255, 255, 255))

    for record in records:
        abbr = record["abbr"]
        if abbr in CALLOUTS:
            continue
        if record["state"] == "Alaska":
            x, y = alaska_project(record["lon"], record["lat"])
            draw_city_label(draw, record, x + 10, y - 18, compact=True)
            continue
        if record["state"] == "Hawaii":
            x, y = hawaii_project(record["lon"], record["lat"])
            draw_city_label(draw, record, x + 5, y - 28, compact=True)
            continue
        x, y = lower_project(record["lon"], record["lat"])
        dx, dy = LABEL_OFFSETS.get(abbr, (0, 0))
        draw_city_label(draw, record, x + dx, y + dy, compact=False)

    for abbr, box_xy in CALLOUTS.items():
        record = records_by_abbr[abbr]
        source_xy = lower_project(record["lon"], record["lat"])
        draw_callout(draw, record, source_xy, box_xy)

    draw_temperature_panels(draw, records)
    draw_legends(draw)
    footer = "说明：仅显示当天预报最高温与代表城市天气，单位为摄氏度。"
    draw_centered(draw, CANVAS_W / 2, 1576, footer, FONTS[18], COLORS["muted"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=95)


def save_weather_data(output_dir: Path, date_str: str, records: list[dict], data_status: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"weather_data_{date_str}.json"
    payload = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "timezone": LOCAL_TZ,
        "data_status": data_status,
        "weather_source": "Open-Meteo Forecast API",
        "geometry_source": GEOJSON_URL,
        "records": records,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def load_dingtalk_config(path: Path = DINGTALK_CONFIG_PATH) -> dict:
    config: dict = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            config.update(json.load(handle))
    env_map = {
        "webhook": "DINGTALK_WEBHOOK",
        "secret": "DINGTALK_SECRET",
        "image_url": "DINGTALK_IMAGE_URL",
        "image_base_url": "DINGTALK_IMAGE_BASE_URL",
        "at_mobiles": "DINGTALK_AT_MOBILES",
        "is_at_all": "DINGTALK_IS_AT_ALL",
    }
    for key, env_key in env_map.items():
        value = os.environ.get(env_key)
        if value:
            if key == "at_mobiles":
                config[key] = [item.strip() for item in value.split(",") if item.strip()]
            elif key == "is_at_all":
                config[key] = value.strip().lower() in {"1", "true", "yes", "y"}
            else:
                config[key] = value.strip()
    return config


def dingtalk_signed_webhook(webhook: str, secret: str | None) -> str:
    if not secret:
        return webhook
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
    joiner = "&" if "?" in webhook else "?"
    return f"{webhook}{joiner}timestamp={timestamp}&sign={sign}"


def dingtalk_image_url(config: dict, image_path: Path) -> str | None:
    explicit_url = config.get("image_url")
    if explicit_url:
        return str(explicit_url)
    base_url = config.get("image_base_url")
    if not base_url:
        return None
    return f"{str(base_url).rstrip('/')}/{image_path.name}"


def weather_summary(records: list[dict]) -> dict:
    valid = [record for record in records if record.get("temperature_c") is not None]
    hottest = sorted(valid, key=lambda record: record["temperature_c"], reverse=True)
    coolest = sorted(valid, key=lambda record: record["temperature_c"])
    rainy_codes = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
    rainy = [record for record in records if int(record.get("weather_code") or 0) in rainy_codes]
    return {"hottest": hottest, "coolest": coolest, "rainy": rainy}


def build_dingtalk_markdown(
    date_str: str,
    records: list[dict],
    image_path: Path,
    image_url: str | None,
    data_status: str,
) -> tuple[str, str]:
    summary = weather_summary(records)
    hottest_lines = [
        f"- {item['state_zh']} {item['city']}：{item['temperature_c']}°C，{item.get('condition_zh', '未知')}"
        for item in summary["hottest"][:8]
    ]
    cool_lines = [
        f"{item['state_zh']} {item['city']} {item['temperature_c']}°C"
        for item in summary["coolest"][:5]
    ]
    rain_lines = [
        f"{item['state_zh']} {item['city']}（{item.get('condition_zh', '未知')}）"
        for item in summary["rainy"][:6]
    ]
    title = f"美国50州天气地图 {date_str}"
    parts = [
        f"### {title}",
        "",
        "**高温重点：**",
        *(hottest_lines or ["- 今日暂无可用温度数据"]),
        "",
        f"**偏凉区域：** {'、'.join(cool_lines) if cool_lines else '暂无'}",
        f"**降雨/雷雨：** {'、'.join(rain_lines) if rain_lines else '暂无明显集中区'}",
        "",
    ]
    if image_url:
        parts.extend([f"![美国50州天气地图]({image_url})", ""])
    else:
        parts.extend(
            [
                "图片已生成到本地：",
                f"`{image_path}`",
                "",
                "如需钉钉消息内直接显示图片，请在配置里填入公网图片链接或图片托管地址前缀。",
                "",
            ]
        )
    if data_status != "fresh":
        parts.append(f"> 数据状态：{data_status}")
    return title, "\n".join(parts)


def send_dingtalk_markdown(
    date_str: str,
    records: list[dict],
    image_path: Path,
    data_status: str,
    config_path: Path = DINGTALK_CONFIG_PATH,
    image_url_override: str | None = None,
) -> bool:
    config = load_dingtalk_config(config_path)
    webhook = config.get("webhook")
    if not webhook:
        print(f"DingTalk skipped: no webhook configured at {config_path}")
        return False

    image_url = image_url_override or dingtalk_image_url(config, image_path)
    title, markdown = build_dingtalk_markdown(date_str, records, image_path, image_url, data_status)
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": markdown},
        "at": {
            "atMobiles": config.get("at_mobiles", []),
            "isAtAll": bool(config.get("is_at_all", False)),
        },
    }
    url = dingtalk_signed_webhook(str(webhook), config.get("secret"))
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    try:
        result = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DingTalk returned non-JSON response: {body}") from exc
    if result.get("errcode") not in (0, "0", None):
        raise RuntimeError(f"DingTalk send failed: {result}")
    print("DingTalk message sent.")
    return True


def load_github_pages_config(path: Path = GITHUB_PAGES_CONFIG_PATH) -> dict:
    config: dict = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            config.update(json.load(handle))
    env_map = {
        "owner": "GITHUB_PAGES_OWNER",
        "repo": "GITHUB_PAGES_REPO",
        "branch": "GITHUB_PAGES_BRANCH",
        "token": "GITHUB_PAGES_TOKEN",
        "pages_base_url": "GITHUB_PAGES_BASE_URL",
    }
    for key, env_key in env_map.items():
        value = os.environ.get(env_key)
        if value:
            config[key] = value.strip()
    config.setdefault("branch", "main")
    config.setdefault("remote_dir", "daily_us_weather_maps")
    return config


def github_api_url(owner: str, repo: str, path: str) -> str:
    owner_q = urllib.parse.quote(owner, safe="")
    repo_q = urllib.parse.quote(repo, safe="")
    path_q = urllib.parse.quote(path, safe="/")
    return f"https://api.github.com/repos/{owner_q}/{repo_q}/contents/{path_q}"


def github_json_request(
    url: str,
    token: str,
    method: str = "GET",
    payload: dict | None = None,
) -> dict | None:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json; charset=utf-8",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "daily-us-weather-map/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == "GET":
            return None
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} failed with HTTP {exc.code}: {details}") from exc
    return json.loads(body) if body else {}


def github_upload_file(
    config: dict,
    local_path: Path,
    remote_path: str,
    commit_message: str,
) -> str:
    required = ["owner", "repo", "token", "pages_base_url"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise RuntimeError(f"GitHub Pages config missing: {', '.join(missing)}")
    owner = str(config["owner"])
    repo = str(config["repo"])
    token = str(config["token"])
    branch = str(config.get("branch", "main"))
    url = github_api_url(owner, repo, remote_path)
    existing = github_json_request(f"{url}?ref={urllib.parse.quote(branch, safe='')}", token)
    payload = {
        "message": commit_message,
        "content": base64.b64encode(local_path.read_bytes()).decode("ascii"),
        "branch": branch,
    }
    if existing and existing.get("sha"):
        payload["sha"] = existing["sha"]
    github_json_request(url, token, method="PUT", payload=payload)
    pages_base_url = str(config["pages_base_url"]).rstrip("/") + "/"
    return pages_base_url + urllib.parse.quote(remote_path, safe="/")


def upload_to_github_pages(
    date_str: str,
    image_path: Path,
    latest_path: Path,
    data_path: Path,
    config_path: Path = GITHUB_PAGES_CONFIG_PATH,
) -> str:
    config = load_github_pages_config(config_path)
    remote_dir = str(config.get("remote_dir", "daily_us_weather_maps")).strip("/")
    dated_remote = f"{remote_dir}/{image_path.name}"
    latest_remote = f"{remote_dir}/{latest_path.name}"
    data_remote = f"{remote_dir}/{data_path.name}"
    commit_message = f"Update weather map {date_str}"
    dated_url = github_upload_file(config, image_path, dated_remote, commit_message)
    github_upload_file(config, latest_path, latest_remote, commit_message)
    github_upload_file(config, data_path, data_remote, commit_message)
    print(f"GitHub Pages image uploaded: {dated_url}")
    return dated_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Chinese US 50-state weather map.")
    parser.add_argument("--date", default=local_today(), help="Output date label, default: today in Asia/Shanghai.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Directory for PNG and JSON outputs.")
    parser.add_argument("--refresh-geojson", action="store_true", help="Re-download state geometry.")
    parser.add_argument("--upload-github-pages", action="store_true", help="Upload generated image/data to GitHub Pages.")
    parser.add_argument(
        "--github-pages-config",
        default=str(GITHUB_PAGES_CONFIG_PATH),
        help="GitHub Pages upload config JSON path. Environment variables can override it.",
    )
    parser.add_argument("--send-dingtalk", action="store_true", help="Send the generated daily report to DingTalk.")
    parser.add_argument(
        "--dingtalk-config",
        default=str(DINGTALK_CONFIG_PATH),
        help="DingTalk config JSON path. Environment variables can override it.",
    )
    parser.add_argument(
        "--no-cache-fallback",
        action="store_true",
        help="Fail instead of rendering from the latest cached weather data if the weather API is unavailable.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    geojson = ensure_geojson(refresh=args.refresh_geojson)

    data_note = ""
    data_status = "fresh"
    try:
        records = fetch_weather(args.date)
    except Exception as exc:
        if args.no_cache_fallback:
            raise
        cached = latest_cached_weather(output_dir)
        if cached is None:
            raise RuntimeError("Weather API failed and no cached weather data exists.") from exc
        records, cache_date = cached
        data_status = f"cached:{cache_date}"
        data_note = f"天气接口暂不可用，本图使用 {cache_date} 的缓存数据"

    output_path = output_dir / f"us_weather_map_{args.date}.png"
    render_map(records, geojson, args.date, output_path, data_note=data_note)
    data_path = save_weather_data(output_dir, args.date, records, data_status)
    latest_path = output_dir / "latest_us_weather_map.png"
    shutil.copyfile(output_path, latest_path)
    print(f"Weather map generated: {output_path}")
    print(f"Latest copy updated: {latest_path}")
    print(f"Weather data saved: {data_path}")
    image_url = None
    if args.upload_github_pages:
        image_url = upload_to_github_pages(
            args.date,
            output_path,
            latest_path,
            data_path,
            config_path=Path(args.github_pages_config).resolve(),
        )
    if args.send_dingtalk:
        send_dingtalk_markdown(
            args.date,
            records,
            output_path,
            data_status,
            config_path=Path(args.dingtalk_config).resolve(),
            image_url_override=image_url,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
