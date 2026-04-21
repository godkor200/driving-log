from typing import TypedDict


class Record(TypedDict):
    timestamp: int
    gps_lat: float | None
    gps_lon: float | None
    speed: float | None


class DetectedEvent(TypedDict):
    event_type: str
    timestamp: int
    detail: str


class ZoneBase(TypedDict):
    name: str
    gps_lat: float
    gps_lon: float
    radius_meters: float


class Zone(ZoneBase):
    _lat_min: float
    _lat_max: float
    _lon_min: float
    _lon_max: float
