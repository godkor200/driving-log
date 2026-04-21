from pydantic import BaseModel, field_validator


class RawRecord(BaseModel):
    timestamp: int
    gps_lat: float | None = None
    gps_lon: float | None = None
    speed: float | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("timestamp must be a positive integer")
        return v

    @field_validator("gps_lat")
    @classmethod
    def lat_in_range(cls, v: float | None) -> float | None:
        if v is not None and not (-90.0 <= v <= 90.0):
            raise ValueError("gps_lat must be between -90 and 90")
        return v

    @field_validator("gps_lon")
    @classmethod
    def lon_in_range(cls, v: float | None) -> float | None:
        if v is not None and not (-180.0 <= v <= 180.0):
            raise ValueError("gps_lon must be between -180 and 180")
        return v

class AnalyzeRequest(BaseModel):
    records: list[RawRecord]


class TripResult(BaseModel):
    trip_id: int
    event_count: int


class AnalyzeResponse(BaseModel):
    trip_count: int
    trips: list[TripResult]


class EventResponse(BaseModel):
    id: int
    event_type: str
    timestamp: int
    detail: dict | None

    model_config = {"from_attributes": True}


class TripDetailResponse(BaseModel):
    id: int
    start_time: int
    end_time: int
    duration_seconds: int
    distance_km: float
    record_count: int
    events: list[EventResponse]

    model_config = {"from_attributes": True}
