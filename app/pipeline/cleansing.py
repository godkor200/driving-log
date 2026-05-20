import numpy as np
from haversine import haversine, Unit

from app.types import Record

MAX_SPEED = 150.0        # km/h 초과 시 속도 이상치로 판단
GPS_JUMP_SPEED = 300.0   # km/h — 연속 좌표 간 암묵적 속도가 이를 초과하면 GPS 점프로 판단


def cleanse(records: list[Record]) -> list[Record]:
    """
    1. timestamp 기준 정렬
    2. 중복 timestamp 제거
    3. GPS 좌표 점프 제거
    4. 결측값 선형 보간  — O(N)
    5. 속도 이상치 선형 보간  — O(N)
    """
    if not records:
        return []

    records = [dict(r) for r in sorted(records, key=lambda r: r["timestamp"])]
    records = _deduplicate_timestamps(records)
    records = _remove_gps_jumps(records)
    records = _interpolate_missing(records)
    records = _interpolate_speed_outliers(records)

    return records


def _deduplicate_timestamps(records: list[Record]) -> list[Record]:
    """동일 timestamp가 여러 레코드인 경우 마지막 레코드만 유지 (정렬 순서 보존)"""
    seen: dict[int, Record] = {}
    for r in records:
        seen[r["timestamp"]] = r
    return list(seen.values())


def _remove_gps_jumps(records: list[Record]) -> list[Record]:
    """
    연속 GPS 좌표 간 암묵적 속도가 GPS_JUMP_SPEED를 초과하면 해당 좌표를 None으로 마킹.
    이후 _interpolate_missing이 주변 유효 좌표로 보간한다.
    """
    for i in range(1, len(records)):
        lat0, lon0 = records[i - 1]["gps_lat"], records[i - 1]["gps_lon"]
        lat1, lon1 = records[i]["gps_lat"], records[i]["gps_lon"]

        if any(v is None for v in (lat0, lon0, lat1, lon1)):
            continue

        dt_sec = records[i]["timestamp"] - records[i - 1]["timestamp"]
        if dt_sec <= 0:
            continue

        dist_km = haversine((lat0, lon0), (lat1, lon1), unit=Unit.KILOMETERS)
        if dist_km / (dt_sec / 3600) > GPS_JUMP_SPEED:
            records[i]["gps_lat"] = None
            records[i]["gps_lon"] = None

    return records


def _interpolate_missing(records: list[Record]) -> list[Record]:
    """
    None 필드를 선형 보간 — np.interp로 벡터화

    유효값 사이는 선형 보간, 경계 밖은 forward/backward fill
    (np.interp 기본 동작: 범위 밖 값은 경계값으로 고정)
    """
    timestamps = np.array([r["timestamp"] for r in records], dtype=float)
    fields = ("gps_lat", "gps_lon", "speed")

    for field in fields:
        values = np.array([r[field] if r[field] is not None else np.nan for r in records], dtype=float)
        valid_mask = ~np.isnan(values)
        if not valid_mask.any():
            continue

        # 유효값 기준으로 전체 구간 보간
        filled = np.interp(timestamps, timestamps[valid_mask], values[valid_mask])
        for i, v in enumerate(filled):
            records[i][field] = float(v)

    return records


def _interpolate_speed_outliers(records: list[Record]) -> list[Record]:
    """
    이상치 속도(음수 또는 MAX_SPEED 초과)를 선형 보간 — np.interp로 벡터화
    """
    timestamps = np.array([r["timestamp"] for r in records], dtype=float)
    speeds = np.array([r["speed"] if r["speed"] is not None else np.nan for r in records], dtype=float)

    valid_mask = ~np.isnan(speeds) & (speeds >= 0) & (speeds <= MAX_SPEED)
    if not valid_mask.any():
        return records

    # 유효 속도 기준으로 전체 구간 보간 — Python 루프 없음
    filled = np.interp(timestamps, timestamps[valid_mask], speeds[valid_mask])
    for i, v in enumerate(filled):
        records[i]["speed"] = float(v)

    return records
