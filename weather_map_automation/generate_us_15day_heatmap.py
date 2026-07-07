#!/usr/bin/env python3
"""
Generate a 15-day US 50-state weather heatmap table in Chinese.

Data source:
- Weather: Open-Meteo Forecast API, no API key required.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from generate_us_weather_map import (
    COLORS,
    DINGTALK_CONFIG_PATH,
    GITHUB_PAGES_CONFIG_PATH,
    LOCAL_TZ,
    OPEN_METEO_URL,
    OUTPUT_DIR,
    STATE_BY_ABBR,
    STATE_BY_NAME,
    dingtalk_signed_webhook,
    github_upload_file,
    load_dingtalk_config,
    load_font,
    load_github_pages_config,
    local_today,
    request_json,
    text_size,
)

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


CANVAS_W = 2800
CANVAS_H = 1740
FONTS = {
    size: load_font(size)
    for size in [12, 13, 14, 15, 16, 18, 20, 22, 24, 26, 28, 30, 34, 42, 56, 64]
}

REGION_ORDER = [
    ("西部", (232, 241, 252), ["AK", "AZ", "CA", "CO", "HI", "ID", "MT", "NV", "NM", "OR", "UT", "WA", "WY"]),
    ("中西部", (236, 249, 235), ["IL", "IN", "IA", "KS", "MI", "MN", "MO", "NE", "ND", "OH", "SD", "WI"]),
    ("南部", (255, 248, 229), ["AL", "AR", "DE", "FL", "GA", "KY", "LA", "MD", "MS", "NC", "OK", "SC", "TN", "TX", "VA", "WV"]),
    ("东北部", (237, 242, 255), ["CT", "ME", "MA", "NH", "NJ", "NY", "PA", "RI", "VT"]),
]


def local_now_iso() -> str:
    if ZoneInfo is None:
        return datetime.now().isoformat(timespec="seconds")
    return datetime.now(ZoneInfo(LOCAL_TZ)).isoformat(timespec="seconds")


def parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text((x0 + (x1 - x0 - w) / 2, y0 + (y1 - y0 - h) / 2 - 1), text, font=font, fill=fill)


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


def temp_fill(temp: int | None) -> tuple[int, int, int]:
    return COLORS[temp_category(temp)]


def temp_text_fill(temp: int | None) -> tuple[int, int, int]:
    category = temp_category(temp)
    if category in {"extreme", "cool"}:
        return (255, 255, 255)
    return COLORS["text"]


def judgment_for_temps(temps: list[int | None]) -> str:
    valid = [item for item in temps if item is not None]
    if not valid:
        return "数据观察"
    peak = max(valid)
    hot_days = sum(1 for item in valid if item >= 30)
    cool_days = sum(1 for item in valid if item <= 19)
    if peak >= 40:
        return "极端高温"
    if peak >= 33 or hot_days >= 5:
        return "防晒重点"
    if cool_days >= 5:
        return "偏凉观察"
    return "普通观察"


def fetch_15day_weather(date_str: str, days: int = 15) -> tuple[list[dict], list[str]]:
    start_date = parse_date(date_str)
    end_date = start_date + timedelta(days=days - 1)
    latitudes = ",".join(f"{item['lat']:.4f}" for item in STATE_BY_NAME.values())
    longitudes = ",".join(f"{item['lon']:.4f}" for item in STATE_BY_NAME.values())
    params = urllib.parse.urlencode(
        {
            "latitude": latitudes,
            "longitude": longitudes,
            "daily": "temperature_2m_max",
            "temperature_unit": "celsius",
            "timezone": "auto",
            "start_date": date_str,
            "end_date": end_date.date().isoformat(),
        }
    )
    payload = request_json(f"{OPEN_METEO_URL}?{params}")
    if isinstance(payload, dict):
        payload = [payload]
    expected_dates = [(start_date + timedelta(days=offset)).date().isoformat() for offset in range(days)]
    records: list[dict] = []
    for base, weather_item in zip(STATE_BY_NAME.values(), payload):
        daily = weather_item.get("daily", {})
        api_dates = daily.get("time") or []
        api_temps = daily.get("temperature_2m_max") or []
        by_date = {
            str(day): None if temp is None else round(float(temp))
            for day, temp in zip(api_dates, api_temps)
        }
        temps = [by_date.get(day) for day in expected_dates]
        valid = [temp for temp in temps if temp is not None]
        record = dict(base)
        record.update(
            {
                "dates": expected_dates,
                "temps": temps,
                "peak_c": max(valid) if valid else None,
                "judgment": judgment_for_temps(temps),
                "timezone": weather_item.get("timezone"),
            }
        )
        records.append(record)
    if len(records) != 50:
        raise RuntimeError(f"Expected 50 weather records, got {len(records)}")
    return records, expected_dates


def latest_cached_heatmap(output_dir: Path) -> tuple[list[dict], list[str], str] | None:
    files = sorted(output_dir.glob("weather_15day_data_*.json"))
    for path in reversed(files):
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            records = payload.get("records")
            dates = payload.get("dates")
            if isinstance(records, list) and len(records) == 50 and isinstance(dates, list) and len(dates) >= 15:
                return records, dates[:15], payload.get("date", path.stem.replace("weather_15day_data_", ""))
        except (OSError, json.JSONDecodeError):
            continue
    return None


def ordered_records(records: list[dict]) -> list[tuple[str, tuple[int, int, int], dict]]:
    by_abbr = {record["abbr"]: record for record in records}
    ordered: list[tuple[str, tuple[int, int, int], dict]] = []
    for region, color, abbrs in REGION_ORDER:
        for abbr in abbrs:
            record = by_abbr.get(abbr)
            if record:
                ordered.append((region, color, record))
    return ordered


def draw_legend_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    title: str,
    subtitle: str,
    outline: tuple[int, int, int],
) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=16, fill=(255, 255, 255), outline=outline, width=3)
    draw.ellipse((x0 + 24, y0 + 20, x0 + 84, y0 + 80), fill=color)
    draw.text((x0 + 112, y0 + 22), title, font=FONTS[24], fill=COLORS["text"])
    draw.text((x0 + 112, y0 + 56), subtitle, font=FONTS[18], fill=outline)


def draw_header_and_legend(draw: ImageDraw.ImageDraw, date_str: str, dates: list[str], data_note: str) -> None:
    draw.rounded_rectangle((1, 1, CANVAS_W - 2, CANVAS_H - 2), radius=10, outline=COLORS["border"], width=2)
    title = "美国50州未来15天天气热力表（摄氏度）"
    tw, _ = text_size(draw, title, FONTS[64])
    draw.text(((CANVAS_W - tw) / 2, 32), title, font=FONTS[64], fill=COLORS["navy"])
    subtitle = f"起始日期：{date_str}  |  每州选1个代表性主要城市  |  每格为当日最高温，颜色越深代表温度越高"
    sw, _ = text_size(draw, subtitle, FONTS[22])
    draw.text(((CANVAS_W - sw) / 2, 105), subtitle, font=FONTS[22], fill=COLORS["muted"])
    if data_note:
        nw, _ = text_size(draw, data_note, FONTS[18])
        draw.text(((CANVAS_W - nw) / 2, 134), data_note, font=FONTS[18], fill=(184, 76, 20))

    y = 174
    gap = 40
    w = 520
    boxes = [
        ((70, y, 70 + w, y + 94), COLORS["extreme"], "极端高温", "≥40°C", (245, 55, 55)),
        ((70 + (w + gap), y, 70 + 2 * w + gap, y + 94), COLORS["hot"], "高温炎热", "30-39°C", (245, 135, 24)),
        ((70 + 2 * (w + gap), y, 70 + 3 * w + 2 * gap, y + 94), COLORS["mild"], "温和舒适", "20-29°C", (131, 144, 156)),
        ((70 + 3 * (w + gap), y, 70 + 4 * w + 3 * gap, y + 94), COLORS["cool"], "低温偏凉", "≤19°C", (68, 151, 231)),
    ]
    for box, color, title, subtitle, outline in boxes:
        draw_legend_card(draw, box, color, title, subtitle, outline)

    scene_box = (70 + 4 * (w + gap), y, CANVAS_W - 70, y + 94)
    draw_legend_card(draw, scene_box, COLORS["navy"], "使用场景", "选品 / 广告 / 区域判断", COLORS["navy"])


def render_heatmap(records: list[dict], dates: list[str], date_str: str, output_path: Path, data_note: str = "") -> None:
    image = Image.new("RGB", (CANVAS_W, CANVAS_H), (248, 250, 253))
    draw = ImageDraw.Draw(image)
    draw_header_and_legend(draw, date_str, dates, data_note)

    x0 = 66
    y0 = 328
    region_w = 92
    city_w = 360
    day_w = 118
    peak_w = 132
    judge_w = 310
    header_h = 70
    row_h = 24
    table_w = region_w + city_w + day_w * 15 + peak_w + judge_w
    table_h = header_h + row_h * 50
    navy = COLORS["navy"]

    draw.rounded_rectangle((x0, y0, x0 + table_w, y0 + table_h), radius=12, fill=(255, 255, 255), outline=(190, 204, 221), width=2)
    draw.rectangle((x0, y0, x0 + table_w, y0 + header_h), fill=navy)

    headers = ["区域", "州 / 代表城市"]
    headers.extend([f"D{idx + 1}\n{day[5:]}" for idx, day in enumerate(dates[:15])])
    headers.extend(["15天峰值", "运营判断"])
    col_x = [x0, x0 + region_w, x0 + region_w + city_w]
    for _ in range(15):
        col_x.append(col_x[-1] + day_w)
    col_x.append(col_x[-1] + peak_w)
    col_x.append(col_x[-1] + judge_w)

    for index, header in enumerate(headers):
        left = col_x[index]
        right = col_x[index + 1]
        parts = header.split("\n")
        if len(parts) == 1:
            draw_centered_text(draw, left, y0, right, y0 + header_h, parts[0], FONTS[22], (255, 255, 255))
        else:
            draw_centered_text(draw, left, y0 + 8, right, y0 + 36, parts[0], FONTS[16], (255, 255, 255))
            draw_centered_text(draw, left, y0 + 36, right, y0 + header_h, parts[1], FONTS[14], (208, 219, 235))

    for x in col_x[1:-1]:
        draw.line((x, y0, x, y0 + table_h), fill=(220, 226, 235), width=1)

    rows = ordered_records(records)
    current_y = y0 + header_h
    row_index = 0
    for region, region_color, record in rows:
        base_fill = (251, 253, 255) if row_index % 2 == 0 else (244, 248, 253)
        draw.rectangle((x0, current_y, x0 + table_w, current_y + row_h), fill=base_fill)
        draw.line((x0, current_y, x0 + table_w, current_y), fill=(218, 225, 235), width=1)
        draw.rectangle((x0, current_y, x0 + region_w, current_y + row_h), fill=region_color)
        city_text = f"{record['abbr']} {record['city']}"
        draw.text((x0 + region_w + 12, current_y + 2), city_text, font=FONTS[15], fill=COLORS["text"])
        temps = record.get("temps", [])[:15]
        for day_idx in range(15):
            temp = temps[day_idx] if day_idx < len(temps) else None
            left = x0 + region_w + city_w + day_idx * day_w
            pill = (left + 8, current_y + 3, left + day_w - 8, current_y + row_h - 3)
            draw.rounded_rectangle(pill, radius=5, fill=temp_fill(temp))
            label = "--" if temp is None else f"{temp}°"
            draw_centered_text(draw, pill[0], pill[1], pill[2], pill[3], label, FONTS[15], temp_text_fill(temp))

        peak = record.get("peak_c")
        peak_left = x0 + region_w + city_w + 15 * day_w
        peak_pill = (peak_left + 8, current_y + 3, peak_left + peak_w - 8, current_y + row_h - 3)
        draw.rounded_rectangle(peak_pill, radius=5, fill=temp_fill(peak))
        draw_centered_text(draw, peak_pill[0], peak_pill[1], peak_pill[2], peak_pill[3], "--" if peak is None else f"{peak}°C", FONTS[15], temp_text_fill(peak))

        judge = record.get("judgment", "普通观察")
        judge_color = {
            "极端高温": COLORS["extreme"],
            "防晒重点": (235, 113, 19),
            "偏凉观察": COLORS["cool"],
            "普通观察": (112, 123, 138),
        }.get(judge, COLORS["muted"])
        draw.text((peak_left + peak_w + 24, current_y + 2), judge, font=FONTS[16], fill=judge_color)

        current_y += row_h
        row_index += 1

    group_start = y0 + header_h
    for region, region_color, abbrs in REGION_ORDER:
        group_h = len(abbrs) * row_h
        draw.rectangle((x0, group_start, x0 + region_w, group_start + group_h), fill=region_color, outline=(213, 223, 235))
        draw_centered_text(draw, x0, group_start, x0 + region_w, group_start + group_h, region, FONTS[28], COLORS["navy"])
        group_start += group_h

    footer_y = y0 + table_h + 28
    draw.text((72, footer_y), "说明：数据来自 Open-Meteo Forecast API；每州选1个代表城市，显示未来15天最高温预测。", font=FONTS[18], fill=COLORS["muted"])
    footer_items = [
        (COLORS["extreme"], "极端高温（≥40°C）"),
        (COLORS["hot"], "高温炎热（30-39°C）"),
        (COLORS["mild"], "温和舒适（20-29°C）"),
        (COLORS["cool"], "低温偏凉（≤19°C）"),
    ]
    lx = 470
    for color, label in footer_items:
        draw.rounded_rectangle((lx, footer_y + 42, lx + 78, footer_y + 72), radius=6, fill=color)
        draw.text((lx + 96, footer_y + 42), label, font=FONTS[18], fill=COLORS["text"])
        lx += 430

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=95)


def save_heatmap_data(output_dir: Path, date_str: str, dates: list[str], records: list[dict], data_status: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"weather_15day_data_{date_str}.json"
    payload = {
        "date": date_str,
        "dates": dates,
        "generated_at": local_now_iso(),
        "timezone": LOCAL_TZ,
        "data_status": data_status,
        "weather_source": "Open-Meteo Forecast API",
        "records": records,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def upload_to_github_pages(date_str: str, image_path: Path, latest_path: Path, data_path: Path, config_path: Path) -> str:
    config = load_github_pages_config(config_path)
    remote_dir = str(config.get("remote_dir", "daily_us_weather_maps")).strip("/")
    dated_remote = f"{remote_dir}/{image_path.name}"
    latest_remote = f"{remote_dir}/{latest_path.name}"
    data_remote = f"{remote_dir}/{data_path.name}"
    commit_message = f"Update 15-day weather heatmap {date_str}"
    dated_url = github_upload_file(config, image_path, dated_remote, commit_message)
    github_upload_file(config, latest_path, latest_remote, commit_message)
    github_upload_file(config, data_path, data_remote, commit_message)
    print(f"GitHub Pages 15-day heatmap uploaded: {dated_url}")
    return dated_url


def dingtalk_image_url(config: dict, image_path: Path) -> str | None:
    explicit_url = config.get("image_url")
    if explicit_url:
        return str(explicit_url)
    base_url = config.get("image_base_url")
    if not base_url:
        return None
    return f"{str(base_url).rstrip('/')}/{image_path.name}"


def build_dingtalk_markdown(date_str: str, records: list[dict], image_path: Path, image_url: str | None, data_status: str) -> tuple[str, str]:
    valid = [record for record in records if record.get("peak_c") is not None]
    hottest = sorted(valid, key=lambda item: item["peak_c"], reverse=True)[:10]
    extreme = [item for item in valid if item["peak_c"] >= 40]
    sunscreen = [item for item in valid if item.get("judgment") == "防晒重点"][:8]
    cool = [item for item in valid if item.get("judgment") == "偏凉观察"][:8]
    extreme_text = "、".join(f"{item['state_zh']} {item['city']} {item['peak_c']}°C" for item in extreme[:8])
    sunscreen_text = "、".join(f"{item['state_zh']} {item['city']}" for item in sunscreen)
    cool_text = "、".join(f"{item['state_zh']} {item['city']}" for item in cool)
    title = f"美国50州未来15天天气热力表 {date_str}"
    parts = [
        f"### {title}",
        "",
        f"**极端高温州：** {extreme_text if extreme_text else '暂无 ≥40°C'}",
        f"**防晒重点：** {sunscreen_text if sunscreen_text else '暂无明显集中区'}",
        f"**偏凉观察：** {cool_text if cool_text else '暂无明显集中区'}",
        "",
        "**15天峰值Top：**",
        *[f"- {item['state_zh']} {item['city']}：{item['peak_c']}°C，{item.get('judgment', '普通观察')}" for item in hottest],
        "",
    ]
    if image_url:
        parts.extend([f"![美国50州未来15天天气热力表]({image_url})", ""])
    else:
        parts.extend(
            [
                "图片已生成到本地：",
                f"`{image_path}`",
                "",
                "如需钉钉消息内直接显示图片，请配置公网图片链接或图片托管地址前缀。",
                "",
            ]
        )
    if data_status != "fresh":
        parts.append(f"> 数据状态：{data_status}")
    return title, "\n".join(parts)


def send_dingtalk_markdown(date_str: str, records: list[dict], image_path: Path, data_status: str, config_path: Path, image_url_override: str | None = None) -> bool:
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
    request = urllib.request.Request(
        dingtalk_signed_webhook(str(webhook), config.get("secret")),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    result = json.loads(body)
    if result.get("errcode") not in (0, "0", None):
        raise RuntimeError(f"DingTalk send failed: {result}")
    print("DingTalk 15-day heatmap message sent.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Chinese 15-day US 50-state weather heatmap table.")
    parser.add_argument("--date", default=local_today(), help="Start date label, default: today in Asia/Shanghai.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Directory for PNG and JSON outputs.")
    parser.add_argument("--upload-github-pages", action="store_true", help="Upload generated image/data to GitHub Pages.")
    parser.add_argument("--github-pages-config", default=str(GITHUB_PAGES_CONFIG_PATH), help="GitHub Pages upload config JSON path.")
    parser.add_argument("--send-dingtalk", action="store_true", help="Send the generated 15-day report to DingTalk.")
    parser.add_argument("--dingtalk-config", default=str(DINGTALK_CONFIG_PATH), help="DingTalk config JSON path.")
    parser.add_argument("--no-cache-fallback", action="store_true", help="Fail instead of rendering from cached data if weather API is unavailable.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    data_note = ""
    data_status = "fresh"
    try:
        records, dates = fetch_15day_weather(args.date)
    except Exception as exc:
        if args.no_cache_fallback:
            raise
        cached = latest_cached_heatmap(output_dir)
        if cached is None:
            raise RuntimeError("Weather API failed and no cached 15-day weather data exists.") from exc
        records, dates, cache_date = cached
        data_status = f"cached:{cache_date}"
        data_note = f"天气接口暂不可用，本表使用 {cache_date} 的缓存数据"

    output_path = output_dir / f"us_weather_15day_heatmap_{args.date}.png"
    render_heatmap(records, dates, args.date, output_path, data_note=data_note)
    data_path = save_heatmap_data(output_dir, args.date, dates, records, data_status)
    latest_path = output_dir / "latest_us_weather_15day_heatmap.png"
    shutil.copyfile(output_path, latest_path)
    print(f"15-day heatmap generated: {output_path}")
    print(f"Latest 15-day heatmap copy updated: {latest_path}")
    print(f"15-day weather data saved: {data_path}")

    image_url = None
    if args.upload_github_pages:
        image_url = upload_to_github_pages(args.date, output_path, latest_path, data_path, Path(args.github_pages_config).resolve())
    if args.send_dingtalk:
        send_dingtalk_markdown(args.date, records, output_path, data_status, Path(args.dingtalk_config).resolve(), image_url_override=image_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
