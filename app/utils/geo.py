import math

from app.types import Zone, ZoneBase


def add_bbox(zones: list[ZoneBase]) -> list[Zone]:
    """
    각 zone에 bounding box 좌표를 사전 계산하여 추가

    haversine(삼각함수) 호출 전 단순 비교로 후보를 걸러내기 위함.
    zone 반경을 감싸는 최소 사각형의 lat/lon 범위를 계산한다.
    """
    for zone in zones:
        d_lat = zone["radius_meters"] / 111_000
        d_lon = zone["radius_meters"] / (111_000 * math.cos(math.radians(zone["gps_lat"])))
        zone["_lat_min"] = zone["gps_lat"] - d_lat
        zone["_lat_max"] = zone["gps_lat"] + d_lat
        zone["_lon_min"] = zone["gps_lon"] - d_lon
        zone["_lon_max"] = zone["gps_lon"] + d_lon
    return zones
