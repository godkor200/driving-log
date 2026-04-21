from sqlalchemy import Column, Integer, Float, String, BigInteger, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Trip(Base):
    """시간 gap 기준으로 분할한 주행 단위"""
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    start_time = Column(BigInteger, nullable=False)
    end_time = Column(BigInteger, nullable=False)
    distance_km = Column(Float, nullable=False)
    record_count = Column(Integer, nullable=False)
    source_hash = Column(String, nullable=True, index=True)

    logs = relationship("DrivingLog", back_populates="trip")
    events = relationship("Event", back_populates="trip")


class DrivingLog(Base):
    """cleansing을 통과한 개별 주행 로그"""
    __tablename__ = "driving_logs"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False, index=True)
    timestamp = Column(BigInteger, nullable=False)
    gps_lat = Column(Float, nullable=True)
    gps_lon = Column(Float, nullable=True)
    speed = Column(Float, nullable=True)  # km/h, cleansing 후에도 None일 수 있음

    trip = relationship("Trip", back_populates="logs")


class Event(Base):
    """탐지된 위험 운전 이벤트"""
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)  # SPEEDING_RESTRICTED_ZONE | SUDDEN_ACCEL | SUDDEN_DECEL
    timestamp = Column(BigInteger, nullable=False)
    detail = Column(String, nullable=True)  # JSON 직렬화된 부가 정보

    trip = relationship("Trip", back_populates="events")
