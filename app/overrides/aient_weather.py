"""Weather and air quality lookup backed by public Open-Meteo endpoints.

The provider needs no API key. Results keep the resolved place name, observation
time and source URL so the model can answer with verifiable data instead of
seasonal guesses.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .registry import register_tool

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

_WEATHER_CODES = {
    0: "晴", 1: "晴到多云", 2: "多云", 3: "阴",
    45: "雾", 48: "冻雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "强阵雨", 82: "特大阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}


def _timeout() -> int:
    try:
        return max(3, min(30, int(os.environ.get("WEATHER_TIMEOUT", 8))))
    except (TypeError, ValueError):
        return 8


def _describe_aqi(value: Any) -> str:
    try:
        index = float(value)
    except (TypeError, ValueError):
        return "未知"
    if index <= 20:
        return "很好"
    if index <= 40:
        return "良好"
    if index <= 60:
        return "中等"
    if index <= 80:
        return "较差"
    if index <= 100:
        return "差"
    return "极差"


def _geocode(location: str) -> dict[str, Any] | None:
    response = requests.get(
        _GEOCODE_URL,
        params={"name": location, "count": 1, "language": "zh", "format": "json"},
        timeout=_timeout(),
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    return results[0] if results else None


def _place_name(place: dict[str, Any]) -> str:
    parts = [place.get("name"), place.get("admin1"), place.get("country")]
    return " · ".join(str(part) for part in parts if part)


@register_tool()
def get_weather(location: str, days: int = 2) -> str:
    """查询指定地点的实时天气、未来预报与空气质量。

    参数:
        location: 地点名称，例如 "上海"、"Tokyo"、"Shanghai Pudong"。
        days: 需要的预报天数，1 到 5，默认 2（今天与明天）。

    返回:
        实况温度、体感、风力、湿度、降水概率、每日高低温与空气质量。
    """
    location = str(location or "").strip()
    if not location:
        return "<tool_error>请提供地点名称。</tool_error>"
    try:
        span = max(1, min(5, int(days)))
    except (TypeError, ValueError):
        span = 2

    try:
        place = _geocode(location)
    except Exception as exc:
        return f"<tool_error>地理编码服务不可用：{type(exc).__name__}</tool_error>"
    if not place:
        return f"<tool_error>没有找到地点「{location}」，请换一个更明确的名称。</tool_error>"

    latitude = place.get("latitude")
    longitude = place.get("longitude")
    timezone = place.get("timezone") or "auto"

    try:
        forecast = requests.get(
            _FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "timezone": timezone,
                "forecast_days": span,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
            },
            timeout=_timeout(),
        )
        forecast.raise_for_status()
        weather = forecast.json()
    except Exception as exc:
        return f"<tool_error>天气接口不可用：{type(exc).__name__}</tool_error>"

    air: dict[str, Any] = {}
    try:
        air_response = requests.get(
            _AIR_QUALITY_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "timezone": timezone,
                "current": "european_aqi,pm2_5,pm10,uv_index",
            },
            timeout=_timeout(),
        )
        air_response.raise_for_status()
        air = air_response.json().get("current") or {}
    except Exception:
        air = {}

    current = weather.get("current") or {}
    units = weather.get("current_units") or {}
    daily = weather.get("daily") or {}

    lines = [
        f"地点：{_place_name(place)}",
        f"观测时间：{current.get('time', '未知')}（{weather.get('timezone', timezone)}）",
        f"实况：{_WEATHER_CODES.get(current.get('weather_code'), '未知天气')}"
        f"，气温 {current.get('temperature_2m', '?')}{units.get('temperature_2m', '°C')}"
        f"，体感 {current.get('apparent_temperature', '?')}{units.get('apparent_temperature', '°C')}",
        f"湿度 {current.get('relative_humidity_2m', '?')}%"
        f"，风速 {current.get('wind_speed_10m', '?')}{units.get('wind_speed_10m', 'km/h')}"
        f"，当前降水 {current.get('precipitation', 0)}{units.get('precipitation', 'mm')}",
    ]

    if air:
        lines.append(
            f"空气质量：欧洲 AQI {air.get('european_aqi', '?')}（{_describe_aqi(air.get('european_aqi'))}）"
            f"，PM2.5 {air.get('pm2_5', '?')} μg/m³，PM10 {air.get('pm10', '?')} μg/m³"
            f"，紫外线指数 {air.get('uv_index', '?')}"
        )

    dates = daily.get("time") or []
    for index, date in enumerate(dates[:span]):
        lines.append(
            f"{date}：{_WEATHER_CODES.get((daily.get('weather_code') or [None])[index], '未知天气')}"
            f"，{(daily.get('temperature_2m_min') or ['?'])[index]}–{(daily.get('temperature_2m_max') or ['?'])[index]}°C"
            f"，降水概率 {(daily.get('precipitation_probability_max') or ['?'])[index]}%"
            f"，日出 {(daily.get('sunrise') or ['?'])[index][-5:]}"
            f"，日落 {(daily.get('sunset') or ['?'])[index][-5:]}"
        )

    lines.append("数据来源：https://open-meteo.com/ （实况与预报），https://open-meteo.com/en/docs/air-quality-api （空气质量）")
    return "\n".join(lines)
