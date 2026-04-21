from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db.session import init_db
from app.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="자율주행 안전 운행 분석 시스템",
    description="자율주행 테스트 차량 로그 데이터를 정제하고 위험 운전 행동을 탐지하는 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)
