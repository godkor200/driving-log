import json

import numpy as np
from haversine import haversine, Unit

from app.types import DetectedEvent, Record, Zone

SUDDEN_CHANGE_THRESHOLD = 10.0      # km/h — 급가속/급감속 기준
RESTRICTED_ZONE_SPEED_LIMIT = 30.0  # km/h — 제한구역 제한 속도


def detect(trip: list[Record], zones: list[Zone]) -> list[DetectedEvent]:
    """
    Trip 내 위험 운전 이벤트 탐지

    반환: 탐지된 이벤트 리스트
    각 이벤트: {"event_type": str, "timestamp": int, "detail": str}
    """
    events = []
    events.extend(_detect_sudden_accel_decel(trip))
    events.extend(_detect_restricted_zone_speeding(trip, zones))
    return events


def _detect_sudden_accel_decel(trip: list[Record]) -> list[DetectedEvent]:
    """
    인접 레코드 간 속도 변화율(km/h per second)이 SUDDEN_CHANGE_THRESHOLD 이상이면 이벤트 생성

    스펙: '1초 단위 시간 변화량 대비 속도가 10km/h 이상 급변한 구간'
    NumPy 벡터화로 rate 배열을 한 번에 계산 후 임계값 초과 인덱스만 이벤트 생성
    """
    if len(trip) < 2:
        return []

    speeds = np.array([r["speed"] if r["speed"] is not None else np.nan for r in trip], dtype=float)
    timestamps = np.array([r["timestamp"] for r in trip], dtype=float)

    time_gaps = np.diff(timestamps)
    speed_diffs = np.diff(speeds)

    # 유효한 쌍: 양쪽 speed가 존재하고 time_gap > 0
    valid = ~np.isnan(speed_diffs) & (time_gaps > 0)
    safe_gaps = np.where(time_gaps > 0, time_gaps, 1.0)  # 0 나누기 방지
    rates = np.where(valid, speed_diffs / safe_gaps, np.nan)  # km/h per second

    event_indices = np.where(valid & (np.abs(rates) >= SUDDEN_CHANGE_THRESHOLD))[0]

    events = []
    for idx in event_indices:
        rate = float(rates[idx])
        event_type = "SUDDEN_ACCEL" if rate > 0 else "SUDDEN_DECEL"
        events.append({
            "event_type": event_type,
            "timestamp": trip[int(idx) + 1]["timestamp"],
            "detail": json.dumps({
                "speed_before": float(speeds[idx]),
                "speed_after": float(speeds[idx + 1]),
                "rate": round(rate, 2),
            }, ensure_ascii=False),
        })

    return events


def _detect_restricted_zone_speeding(
    trip: list[Record],
    zones: list[Zone],
) -> list[DetectedEvent]:
    """
    제한구역 반경 내에서 RESTRICTED_ZONE_SPEED_LIMIT 초과 시 이벤트 생성

    speed > 30 인 레코드만 zone 비교 대상으로 필터링하여 연산 최소화
    """
    events = []
    for record in trip:
        if record["speed"] is None or record["gps_lat"] is None or record["gps_lon"] is None:
            continue  # 복구 불가능한 레코드는 건너뜀

        if record["speed"] <= RESTRICTED_ZONE_SPEED_LIMIT:
            continue

        for zone in zones:
            if not (zone["_lat_min"] <= record["gps_lat"] <= zone["_lat_max"]
                    and zone["_lon_min"] <= record["gps_lon"] <= zone["_lon_max"]):
                continue
            dist_m = haversine(
                (record["gps_lat"], record["gps_lon"]),
                (zone["gps_lat"], zone["gps_lon"]),
                unit=Unit.METERS,
            )
            if dist_m <= zone["radius_meters"]:
                events.append({
                    "event_type": "SPEEDING_RESTRICTED_ZONE",
                    "timestamp": record["timestamp"],
                    "detail": json.dumps({
                        "zone_name": zone["name"],
                        "speed": record["speed"],
                        "distance_m": round(dist_m, 1),
                    }, ensure_ascii=False),
                })
                break  # 한 레코드에서 여러 zone에 걸쳐도 이벤트는 1개

    return events
