from haversine import haversine, Unit

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

    total = 0.0
    for i in range(1, len(records)):
        lat0, lon0 = records[i - 1]["gps_lat"], records[i - 1]["gps_lon"]
        lat1, lon1 = records[i]["gps_lat"], records[i]["gps_lon"]
        if any(v is None for v in (lat0, lon0, lat1, lon1)):
            continue
        total += haversine((lat0, lon0), (lat1, lon1), unit=Unit.KILOMETERS)

    return round(total, 4)
