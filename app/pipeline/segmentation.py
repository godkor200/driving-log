from haversine import haversine, Unit

from app.types import Record

GAP_THRESHOLD = 300  # 5분 이상 공백이면 새 Trip으로 분리


def segment(records: list[Record]) -> list[list[Record]]:
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
