# 실시간 차량 운행 로그 분석 시스템을 만들며 배운 것

이 프로젝트는 차량에서 발생하는 raw 주행 로그를 실시간으로 받아 정제하고 Trip 단위로 나눈 뒤 위험 운전 이벤트를 탐지해 DB에 저장하는 백엔드 시스템이다.

처음 관심은 보간이었다. 이전에 케이팝레이더 프로젝트를 하면서 시간에 따라 변하는 데이터를 다룰 일이 있었다. 그런데 실제 데이터는 항상 깔끔하게 이어지지 않았다. 중간 값이 비어 있거나 특정 시점의 값이 이상하게 튀는 경우가 있었다. 그때 "이런 값을 사람이 매번 확인해서 고치는 대신 자동으로 보간할 수 없을까"라는 생각을 했다.

처음에는 단순히 빠진 값을 채우는 문제라고 생각했다. 하지만 조금 더 공부해보니 결측값 보간은 전체 데이터 처리 흐름의 한 부분이었다. 값이 비어 있으면 어떻게 채울지 정해야 하고 값이 너무 이상하면 버릴지 보정할지 정해야 한다. 또 데이터가 계속 들어온다면 어느 단위로 모아서 처리할지도 필요하다. 같은 데이터가 다시 들어왔을 때 중복 저장을 막는 방법도 필요하다.

그래서 이 프로젝트에서는 차량 운행 로그라는 도메인을 잡았다. 차량 로그는 timestamp와 GPS 좌표 그리고 속도를 가진다. 이 데이터는 시계열 데이터라서 보간과 이상치 처리의 이유가 자연스럽다. 또 GPS를 이용한 거리 계산과 제한구역 탐지까지 연결할 수 있어서 수학적 계산과 백엔드 파이프라인을 같이 공부하기 좋았다.

## 전체 흐름

프로젝트의 처리 흐름은 다음과 같다.

```text
Raw Records
  -> Cleansing
  -> Segmentation
  -> Detection
  -> DB 저장
  -> API 조회
```

실시간 경로에서는 Kafka의 `driving-logs` 토픽을 구독한다. consumer는 메시지를 받자마자 한 건씩 처리하지 않는다. 10초 동안 버퍼에 모은 뒤 한 번에 파이프라인을 실행한다.

```text
Kafka topic
  -> 10초 윈도우 버퍼
  -> 정제
  -> Trip 분리
  -> 위험 이벤트 탐지
  -> PostgreSQL 저장
```

이렇게 만든 이유는 각 로직이 단건 데이터보다 연속된 데이터를 필요로 하기 때문이다. 결측 GPS를 보간하려면 앞뒤 유효값이 필요하다. Trip을 나누려면 인접 timestamp의 간격을 봐야 한다. 급가속과 급감속도 이전 속도와 현재 속도의 차이를 계산해야 한다.

즉 이 프로젝트의 핵심은 실시간으로 들어오는 데이터를 작은 batch처럼 다루는 것이다.

## Kafka와 10초 윈도우

Kafka는 producer가 보낸 메시지를 topic에 쌓아두고 consumer가 필요한 속도로 가져가 처리할 수 있게 해준다. 차량 로그처럼 계속 생성되는 데이터에는 이런 구조가 잘 맞는다.

차량이 로그를 생성하는 속도와 서버가 분석하는 속도는 항상 같지 않다. 순간적으로 로그가 많이 들어올 수도 있고 DB 저장이 잠깐 느려질 수도 있다. Kafka를 사이에 두면 producer와 consumer가 직접 강하게 묶이지 않는다.

consumer는 다음 방식으로 움직인다.

```python
buffer = []
last_flush = time.time()

while True:
    try:
        batch = consumer.poll(timeout_ms=1000)
    except Exception:
        log.exception("Kafka poll failed; retrying...")
        continue

    for messages in batch.values():
        for msg in messages:
            buffer.append(msg.value)

    size_exceeded = len(buffer) >= MAX_BUFFER_SIZE
    time_exceeded = buffer and time.time() - last_flush >= FLUSH_INTERVAL
    if size_exceeded or time_exceeded:
        try:
            process_batch(buffer)
            consumer.commit()
        except Exception:
            log.exception("Batch processing failed")
        finally:
            buffer = []
            last_flush = time.time()
```

flush 조건은 두 가지다. 시간 조건(`FLUSH_INTERVAL`)과 크기 조건(`MAX_BUFFER_SIZE`)이 OR로 연결된다. 메시지가 폭발적으로 유입될 때 buffer가 무제한으로 쌓이는 OOM 위험을 막기 위해서다.

처리 성공 후에만 `consumer.commit()`을 호출한다(`enable_auto_commit=False`). 자동 커밋을 쓰면 poll 직후 offset이 커밋되어 `process_batch`가 실패해도 해당 메시지가 유실된다. 수동 커밋은 처리 완료를 보장한 뒤 offset을 전진시키는 at-least-once 보장이다.

`buffer = []`는 `finally` 블록 안에 있다. 예외가 발생해도 반드시 초기화된다. 이전에는 `process_batch` 예외 시 buffer가 초기화되지 않아 다음 flush 때 같은 데이터가 중복으로 재처리됐다.

10초 윈도우는 실시간성과 처리 효율 사이의 타협이다. 윈도우가 너무 짧으면 pipeline과 DB insert가 너무 자주 실행된다. 윈도우가 너무 길면 분석 결과가 늦게 나온다. 이 프로젝트에서는 실시간성을 크게 해치지 않으면서도 batch 처리 이점을 얻기 위해 10초를 사용했다.

## 결측값과 이상치 보간

차량 로그에는 보통 다음 값이 들어 있다.

```json
{
  "timestamp": 1710000000,
  "gps_lat": 37.5,
  "gps_lon": 127.0,
  "speed": 42.0
}
```

하지만 현실적인 로그에서는 `gps_lat`이나 `gps_lon` 혹은 `speed`가 `None`일 수 있다. 속도가 음수로 들어오거나 일반적인 도로 주행에서 보기 어려운 값이 들어올 수도 있다. 또 동일 timestamp를 가진 레코드가 중복으로 들어오거나 GPS 수신 오류로 위치가 순간적으로 수백 km 튀는 경우도 생긴다.

cleansing은 다음 순서로 동작한다.

```text
1. timestamp 기준 정렬
2. 중복 timestamp 제거
3. GPS 좌표 점프 제거
4. 결측값 선형 보간
5. 속도 이상치 선형 보간
```

이 프로젝트에서는 속도가 `0 <= speed <= 150` 범위를 벗어나면 이상치로 판단한다. 결측값과 이상치는 모두 "신뢰할 수 없는 관측치"로 보고 주변의 유효한 값으로부터 추정한다.

보간에는 `np.interp`를 사용했다. 핵심은 선형보간이다.

시간 `x0`에서 값이 `y0`이고 시간 `x1`에서 값이 `y1`일 때 그 사이 시간 `x`의 보간값은 다음과 같다.

```text
y = y0 + (x - x0) / (x1 - x0) * (y1 - y0)
```

예를 들어 10초에 속도가 20km/h이고 20초에 속도가 40km/h라면 15초의 속도는 30km/h로 추정할 수 있다.

```text
y = 20 + (15 - 10) / (20 - 10) * (40 - 20)
  = 30
```

코드에서는 timestamp 배열과 값 배열을 만든 뒤 유효한 값만 mask로 고른다.

```python
timestamps = np.array([...], dtype=float)
values = np.array([...], dtype=float)

valid_mask = ~np.isnan(values)
filled = np.interp(
    timestamps,
    timestamps[valid_mask],
    values[valid_mask],
)
```

`np.interp(x, xp, fp)`는 `xp`에 있는 알려진 x좌표와 `fp`에 있는 알려진 y값을 기준으로 `x` 위치의 값을 선형보간한다. Python for-loop로 한 건씩 처리하는 대신 NumPy 배열 연산으로 처리하기 때문에 데이터가 커질수록 유리하다.

속도 이상치는 유효성 조건만 다르게 둔다.

```python
valid_mask = (
    ~np.isnan(speeds)
    & (speeds >= 0)
    & (speeds <= MAX_SPEED)
)
```

정상 속도만 기준점으로 삼고 음수나 150km/h 초과 값은 보간 대상으로 본다. 덕분에 결측값과 이상치를 같은 수학적 틀로 처리할 수 있다.

### 중복 timestamp 제거

같은 timestamp를 가진 레코드가 두 개 이상 들어올 수 있다. 이 경우 보간의 기준이 되는 x축(timestamp)에 중복이 생겨 `np.interp`가 잘못된 결과를 낼 수 있다. 정렬 이후 dict를 사용해 마지막 레코드만 남긴다.

```python
seen: dict[int, Record] = {}
for r in records:
    seen[r["timestamp"]] = r
return list(seen.values())
```

Python 3.7+에서 dict는 삽입 순서를 보존하므로 정렬 순서가 그대로 유지된다.

### GPS 좌표 점프 탐지

GPS 수신 오류가 발생하면 차량이 실제로 이동하지 않았음에도 좌표가 수백 km 떨어진 곳으로 튀는 경우가 있다. 속도 이상치와 달리 GPS 좌표는 유효 범위 자체는 정상이라서 단순 범위 검사로는 걸러낼 수 없다.

그래서 연속 좌표 간 "암묵적 속도"를 계산한다.

```text
implied_speed = 두 좌표 간 haversine 거리 / 시간 간격
```

이 값이 300km/h를 초과하면 물리적으로 불가능한 이동으로 보고 해당 좌표를 `None`으로 마킹한다. 이후 `_interpolate_missing`이 앞뒤 유효 좌표로 선형 보간한다.

```python
dist_km = haversine((lat0, lon0), (lat1, lon1), unit=Unit.KILOMETERS)
if dist_km / (dt_sec / 3600) > GPS_JUMP_SPEED:
    records[i]["gps_lat"] = None
    records[i]["gps_lon"] = None
```

## Trip 분리와 거리 계산

정제된 레코드는 Trip 단위로 나눈다. 이 프로젝트에서는 인접 timestamp 사이가 5분 이상 벌어지면 새로운 Trip으로 판단한다.

```text
gap = current.timestamp - previous.timestamp

gap >= 300초 -> 새로운 Trip
```

Trip이 나뉘면 각 Trip의 이동 거리를 계산한다. 여기서 GPS 좌표는 평면 좌표가 아니다. 위도와 경도는 지구 표면 위의 좌표이기 때문에 단순한 피타고라스 계산으로는 정확하지 않다.

그래서 haversine 공식을 사용했다. haversine은 두 위도와 경도 좌표 사이의 대권거리를 계산하는 공식이다.

```text
a = sin²(Δlat / 2)
  + cos(lat1) * cos(lat2) * sin²(Δlon / 2)

d = 2R * asin(sqrt(a))
```

여기서 `R`은 지구 반지름이다. haversine 공식은 지구를 완전한 구로 가정하는 근사다. 실제 지구는 극이 납작한 타원체라서 더 정확한 Vincenty 공식 같은 타원체 모델을 쓸 수도 있다.

그런데 이 프로젝트에서 haversine의 오차가 실제로 얼마인지 계산해보면 판단이 달라진다.

haversine과 타원체 모델의 오차는 위도에 따라 다르지만 한국(위도 37°N 근방)에서는 약 0.1~0.3% 수준이다. 도심 Trip 거리를 20km라고 가정하면 오차는 20~60m다. 이 시스템은 Trip 총 거리와 급가속 탐지에 거리 계산을 쓰는데 수십 미터 오차가 결과에 영향을 주지 않는다. 제한구역 탐지도 반경이 수백 미터 단위라서 마찬가지다.

반면 Vincenty는 반복 수렴 알고리즘이라 구현 복잡도가 높고 거의 antipodal(정반대 지점)인 좌표에서 수렴하지 않는 엣지 케이스도 있다. 이 프로젝트의 정밀도 요구를 haversine이 충족하기 때문에 더 복잡한 모델을 도입할 이유가 없다.

Trip 안에 레코드가 `N`개 있으면 이동 구간은 `N - 1`개다.

```text
record[0] -> record[1]
record[1] -> record[2]
record[2] -> record[3]
```

각 구간을 Python loop로 계산할 수도 있지만 이 프로젝트에서는 NumPy 배열로 한 번에 계산했다.

```python
lat1 = np.radians(lats[:-1][valid])
lat2 = np.radians(lats[1:][valid])
lon1 = np.radians(lons[:-1][valid])
lon2 = np.radians(lons[1:][valid])

d_lat = lat2 - lat1
d_lon = lon2 - lon1

a = np.sin(d_lat / 2) ** 2 \
    + np.cos(lat1) * np.cos(lat2) * np.sin(d_lon / 2) ** 2

distances_km = 2 * 6371.0 * np.arcsin(np.sqrt(a))
```

GPS가 없는 구간은 NaN mask로 제외한다. 계산 가능한 구간만 거리 합산에 포함한다.

## 위험 이벤트 탐지

이 프로젝트에서 탐지하는 이벤트는 크게 두 가지다.

- 급가속과 급감속
- 제한구역 과속

급가속과 급감속은 속도 변화율로 판단한다.

```text
rate = (speed_after - speed_before) / time_gap
```

단순히 속도가 20km/h 변했다는 사실만으로는 충분하지 않다. 20초 동안 20km/h가 변한 것과 1초 동안 20km/h가 변한 것은 위험도가 다르다. 그래서 시간으로 나눈 변화율을 사용한다.

이 프로젝트에서는 변화율의 절댓값이 `10km/h/s` 이상이면 이벤트로 본다.

```text
rate >= 10  -> SUDDEN_ACCEL
rate <= -10 -> SUDDEN_DECEL
```

제한구역 과속은 속도가 30km/h를 초과하고 차량 위치가 제한구역 반경 안에 있을 때 발생한다.

```text
speed > 30km/h
AND
distance(car, zone_center) <= zone.radius
```

문제는 모든 로그와 모든 제한구역을 haversine으로 비교하면 비용이 크다는 점이다. 레코드가 `N`개이고 zone이 `M`개라면 단순 비교는 `O(N * M)`이다. 게다가 haversine은 삼각함수를 사용하므로 일반 숫자 비교보다 비싸다.

그래서 각 제한구역마다 bounding box를 미리 계산했다. 제한구역의 원을 감싸는 사각형을 먼저 만들고 그 안에 들어오는 후보만 haversine으로 확인한다.

위도 1도는 대략 111km다.

```text
delta_lat = radius_meters / 111000
```

경도 1도는 위도에 따라 실제 거리가 달라진다.

```text
delta_lon = radius_meters / (111000 * cos(latitude))
```

이렇게 구한 범위로 먼저 필터링한다.

```text
lat_min <= car_lat <= lat_max
lon_min <= car_lon <= lon_max
```

차량 위치가 bounding box 밖이면 원 안에 있을 수 없다. 따라서 haversine 계산을 생략한다. 이 방식은 최악의 시간복잡도 자체를 완전히 바꾸지는 않지만 실제 실행 시간에서 비싼 거리 계산 횟수를 크게 줄인다.

## DB 저장과 멱등성

Trip 하나에는 많은 DrivingLog가 포함될 수 있다. 레코드가 10만 개라면 ORM 객체를 10만 개 만들고 session에 하나씩 추가하는 방식은 부담이 크다.

그래서 SQLAlchemy 2.0 Core bulk insert를 사용했다.

```python
db.execute(insert(DrivingLog), [
    {
        "trip_id": trip.id,
        "timestamp": r["timestamp"],
        "gps_lat": r["gps_lat"],
        "gps_lon": r["gps_lon"],
        "speed": r["speed"],
    }
    for r in trip_records
])
```

Trip은 먼저 ORM 객체로 만들고 `flush()`를 호출한다. 그래야 DB가 생성한 `trip.id`를 얻을 수 있다. 그 다음 DrivingLog와 Event는 이 `trip.id`를 사용해 bulk insert한다.

같은 데이터가 다시 들어왔을 때 중복 저장을 막기 위해 SHA-256 기반 source hash도 추가했다.

```python
content = json.dumps([
    {
        "t": r["timestamp"],
        "la": r["gps_lat"],
        "lo": r["gps_lon"],
        "s": r["speed"],
    }
    for r in records
])

source_hash = sha256(content.encode()).hexdigest()
```

같은 입력은 항상 같은 hash를 만든다. 그래서 저장 전에 같은 `source_hash`를 가진 Trip이 있는지 확인한다.

```text
같은 hash가 있다 -> 기존 trip_id 반환
같은 hash가 없다 -> 새 Trip 저장
```

이 성질을 멱등성이라고 한다. 같은 요청을 여러 번 보내도 시스템의 최종 상태가 한 번 보낸 것과 같아지는 성질이다.

멱등성은 API 경로뿐 아니라 Kafka consumer에도 동일하게 적용했다. consumer는 처리 실패 시 Kafka offset을 커밋하지 않고 재시작하면 같은 메시지를 다시 받는다. 이때 source_hash 체크 없이 재처리하면 같은 Trip이 중복 저장된다.

DB 레벨에서도 `source_hash`에 unique constraint를 걸었다. 애플리케이션 레벨 중복 체크와 DB 레벨 제약이 함께 있어야 동시 요청이 들어올 때 race condition으로 발생하는 중복 삽입을 막을 수 있다. 두 요청이 동시에 hash 조회를 통과해도 한 쪽의 commit이 `IntegrityError`를 내고 해당 요청은 이미 저장된 Trip을 반환한다.

```text
check (hash 없음) -> insert -> commit
                  ↑ 동시 요청이 여기서 같은 결과를 보면?
                  -> 한 쪽은 IntegrityError -> 기존 trip 반환
```

트랜잭션은 Trip 단위로 개별 commit한다. 여러 Trip을 한 트랜잭션으로 묶으면 한 Trip의 IntegrityError가 이미 성공한 다른 Trip의 변경까지 롤백한다.

## 입력 검증과 OOM 방어

파이프라인은 데이터를 메모리에 올려 처리한다. records 리스트와 NumPy 배열 그리고 bulk insert용 dict 리스트가 모두 메모리를 사용한다. 입력이 무제한으로 들어오면 서버가 버티기 어렵다.

그래서 API 경로에는 `MAX_RECORDS = 100_000` 가드를 두었다.

```text
records 수 > 100000 -> 413 Payload Too Large
```

또 Pydantic `field_validator`로 timestamp와 GPS 범위 그리고 속도를 검증한다.

```text
0 < timestamp <= 4,102,444,800   (year 2100 상한)
-90 <= gps_lat <= 90
-180 <= gps_lon <= 180
speed >= 0
```

위도와 경도는 지구 좌표계의 정의상 범위가 정해져 있다. 위도는 `-90`에서 `90`이고 경도는 `-180`에서 `180`이다. 이 범위를 벗어나는 값은 보간할 대상이 아니라 잘못된 입력이다.

timestamp 상한은 year 2100에 해당하는 Unix epoch 초 값이다. 이 값을 초과하면 밀리초 단위 timestamp가 실수로 들어온 것으로 판단한다. 밀리초 timestamp가 들어오면 인접 레코드 간 시간 간격이 1000배 커져 급가속·급감속 탐지의 변화율이 1000분의 1로 줄어들고 이벤트가 전혀 탐지되지 않는 조용한 버그가 생긴다.

속도 음수 검사는 cleansing에서도 이상치로 처리되지만 잘못된 입력을 내부 로직까지 통과시키지 않기 위해 API 경계에서도 차단한다.

잘못된 입력은 pipeline에 들어오기 전에 422 응답으로 거절한다. 이렇게 하면 내부 로직은 최소한 좌표 범위와 timestamp 단위가 정상이라는 전제를 가지고 동작할 수 있다.

Kafka consumer buffer도 `MAX_BUFFER_SIZE`(기본값 50,000건)로 상한을 둔다. API는 요청 크기가 제한되지만 consumer는 Kafka에서 연속으로 메시지를 받기 때문에 `FLUSH_INTERVAL` 동안 누적량이 무제한으로 늘어날 수 있다. 크기 조건이 시간 조건보다 먼저 충족되면 즉시 flush한다.

## 마무리

이 프로젝트는 보간을 자동화할 수 없을까 하는 작은 질문에서 시작했다. 하지만 직접 만들다 보니 보간은 전체 파이프라인의 한 부분이었다. 실시간 수신과 시간 윈도우 처리 그리고 결측값 보간과 이상치 처리가 필요했다. 지리 좌표를 다루기 위해 haversine 공식을 공부했고 제한구역 탐지를 빠르게 만들기 위해 bounding box 필터를 붙였다. 대량 저장을 위해 bulk insert를 사용했고 같은 데이터가 다시 들어와도 안전하도록 SHA-256 기반 멱등성도 추가했다.

실제 서비스 환경을 고려하다 보니 추가로 다뤄야 할 문제들이 있었다. GPS 수신 오류로 좌표가 순간적으로 튀는 GPS 점프 현상 중복 timestamp 처리 밀리초 단위 timestamp가 실수로 들어오는 경우 그리고 Kafka consumer에서 처리 실패 후 재시작 시 중복 적재 문제와 buffer 무제한 누적으로 인한 OOM 위험이었다.

결국 이 프로젝트에서 공부한 것은 "데이터가 완벽하지 않을 때 백엔드가 어떻게 책임지고 다룰 것인가"였다. 차량 로그를 정제하고 계산하고 저장하며 다시 들어온 데이터와 실제 주행 환경의 노이즈까지 안전하게 처리하는 흐름을 직접 구현해본 프로젝트라고 설명할 수 있다.

## 포트폴리오용 요약

차량 주행 로그를 Kafka 기반으로 실시간 수신하고 시간 윈도우 단위로 정제와 Trip 분리 그리고 위험 이벤트 탐지를 수행하는 백엔드 파이프라인을 구현했다. cleansing은 중복 timestamp 제거와 GPS 좌표 점프 탐지(암묵적 속도 300km/h 초과 시 None 마킹 후 보간)를 포함해 실제 주행 환경의 노이즈를 방어한다. 결측값과 이상치는 `np.interp` 기반 선형보간으로 처리하고 이동 거리는 NumPy 벡터화 haversine으로 계산해 Python loop 비용을 줄였다. 제한구역 과속 탐지는 bounding box 사전 필터로 비싼 거리 계산 후보를 줄였으며 SQLAlchemy 2.0 Core bulk insert로 대량 로그 저장을 최적화했다. 멱등성은 SHA-256 source hash를 API와 Kafka consumer 양쪽에 적용하고 DB unique constraint와 IntegrityError 처리로 동시 요청 race condition까지 방어했다. OOM은 API `MAX_RECORDS`와 Kafka buffer `MAX_BUFFER_SIZE` 두 지점에서 막고 Pydantic validator로 timestamp 단위 오류(밀리초 혼입)와 음수 속도를 API 경계에서 차단했다.
