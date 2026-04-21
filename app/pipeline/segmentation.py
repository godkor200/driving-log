import numpy as np

from app.types import Record

GAP_THRESHOLD = 300  # 5분 이상 공백이면 새 Trip으로 분리


def segment(records: list[Record]) -> list[list[Record]]:
    """
    timestamp 공백 기준으로 records를 Trip 단위로 분리

    - cleanse() 이후 정렬된 records를 입력으로 받는다
    - 인접 레코드 간 timestamp 차이가 GAP_THRESHOLD 이상이면 새 Trip 시작
    """
    if not records:
        return []

    trips = []
    current_trip = [records[0]]

    for i in range(1, len(records)):
        gap = records[i]["timestamp"] - records[i - 1]["timestamp"]
        if gap >= GAP_THRESHOLD:
            trips.append(current_trip)
            current_trip = []
        current_trip.append(records[i])

    trips.append(current_trip)
    return trips


def calc_distance_km(records: list[Record]) -> float:
    """
    Trip 내 인접 GPS 좌표 간 거리 합산 — NumPy 벡터화로 O(N) 연산 최소화

    GPS가 None인 구간은 NaN 마스킹으로 제외하고 계산 가능한 구간만 합산
    반환값은 소수점 4자리로 반올림
    """
    if len(records) < 2:
        return 0.0

    lats = np.array([r["gps_lat"] if r["gps_lat"] is not None else np.nan for r in records])
    lons = np.array([r["gps_lon"] if r["gps_lon"] is not None else np.nan for r in records])

    # 인접 쌍 중 양쪽 모두 유효한 GPS를 가진 구간만 선택
    valid = ~(np.isnan(lats[:-1]) | np.isnan(lons[:-1]) | np.isnan(lats[1:]) | np.isnan(lons[1:]))
    if not valid.any():
        return 0.0

    lat1 = np.radians(lats[:-1][valid])
    lat2 = np.radians(lats[1:][valid])
    lon1 = np.radians(lons[:-1][valid])
    lon2 = np.radians(lons[1:][valid])

    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    a = np.sin(d_lat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(d_lon / 2) ** 2
    distances_km = 2 * 6371.0 * np.arcsin(np.sqrt(a))

    return round(float(distances_km.sum()), 4)
