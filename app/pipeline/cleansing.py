import numpy as np

from app.types import Record

MAX_SPEED = 150.0  # km/h 초과 시 이상치로 판단


def cleanse(records: list[Record]) -> list[Record]:
    """
    1. timestamp 기준 정렬
    2. 결측값 선형 보간  — O(N)
    3. 속도 이상치 선형 보간  — O(N)
    """
    if not records:
        return []

    records = sorted(records, key=lambda r: r["timestamp"])
    records = _interpolate_missing(records)
    records = _interpolate_speed_outliers(records)

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

        # 유효값 기준으로 전체 구간 보간 — Python 루프 없음
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
