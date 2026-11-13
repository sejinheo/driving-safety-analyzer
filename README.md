# 자율주행 안전 운행 분석 시스템

자율주행 테스트 차량의 주행 로그(JSON)를 수신하여 데이터를 정제하고, Trip 단위로 분리한 뒤 위험 운전 이벤트를 탐지해 PostgreSQL에 저장하는 백엔드 시스템.

로그 하나를 분석하는 작업 단위를 **Run**, Run 안에서 차량(**Vehicle**)별 연속 주행 구간을 **Trip**, Trip을 구성하는 초 단위 GPS/속도 데이터를 **Point**라 부른다.

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| Language | Python 3.12 |
| Web Framework | FastAPI 0.162.2 |
| Database | PostgreSQL 17 (PostGIS) |
| ORM / DB Driver | SQLAlchemy 2.1.8 / psycopg 3.3.8 |
| Data Processing | Polars 2.1.0 / NumPy 2.5.4 |
| Streaming JSON Parser | ijson 3.6.0 (yajl2_c backend) |

---

## 실행 및 API 사용

### 1. 사전 조건

- Docker, Docker Compose 설치

### 2. 컨테이너 시작

```bash
docker compose up -d
```

DB 헬스체크가 통과할 때까지 API 컨테이너가 대기하므로 별도 순서 조정 없이 위 명령어 하나로 충분하다.

### 3. 테스트

#### 방법 A — 웹 UI (브라우저)

1. http://localhost:8001 접속
2. 우측 상단 **school_zones.json 업로드** → `DB 적재` 클릭
3. 좌측 **driving_log.json 업로드** → `데이터 분석 및 적재` 클릭
4. 상태 표시줄이 `COMPLETED`로 바뀌면 Trip 목록이 자동으로 표시됨
5. Trip 카드를 클릭하면 주행 거리, 소요 시간, 이벤트 목록 확인 가능
6. 이전 분석 결과는 Run ID로 불러올 수 있음

#### 방법 B — curl

**① 보호구역 데이터 등록** (분석 전 반드시 먼저 실행)

```bash
# /path/to/school_zones.json 을 실제 파일 경로로 변경
curl -X POST http://localhost:8001/zones \
  -F "file=@/path/to/school_zones.json"
```

**② 분석 시작**

```bash
# /path/to/driving_log.json 을 실제 파일 경로로 변경
curl -X POST http://localhost:8001/analyze \
  -F "file=@/path/to/driving_log.json"
```

응답 예시:
```json
{ "run_id": 1, "status": "PENDING" }
```

분석은 백그라운드 스레드에서 처리된다. 아래 로그로 완료를 확인한 뒤 Trip을 조회한다.

```bash
docker compose logs -f api
# analysis_completed 로그가 출력되면 완료
```

**③ Trip 조회**

```bash
curl http://localhost:8001/trips/1
```

**vehicle_id 지정** (로그에 vehicle_id 필드가 없을 때 사용할 기본값)

```bash
curl -X POST "http://localhost:8001/analyze?vehicle_id=V001" \
  -F "file=@/path/to/driving_log.json"
```

---

## API 명세

### POST /zones _(과제 명세 외 추가 구현)_

분석에 사용할 보호구역 데이터를 등록한다. `POST /analyze` 호출 전에 먼저 실행해야 한다.

**Request**

| 방식 | Content-Type | 설명 |
|------|-------------|------|
| 파일 업로드 | `multipart/form-data` | `file` 필드에 `school_zones.json` 첨부 (필수) |

**Response `200 OK`**

```json
{ "inserted": 10 }
```

**Error Responses**

| Status | code | 설명 |
|--------|------|------|
| 422 | `INVALID_LOG_FORMAT` | JSON 파싱 불가 |
| 422 | `INVALID_ZONE_DATA` | 배열 원소가 객체가 아님 |

---

### POST /analyze

분석 작업을 접수하고 즉시 `run_id`를 반환한다. 실제 처리는 백그라운드 스레드에서 진행된다.

**Request**

| 방식 | Content-Type | 설명 |
|------|-------------|------|
| 파일 업로드 | `multipart/form-data` | `file` 필드에 JSON 파일 첨부 (필수) |

| Query Parameter | 타입 | 필수 | 설명 |
|----------------|------|------|------|
| `vehicle_id` | string | No | 로그에 vehicle_id가 없을 때 사용할 기본값 |

**Response `202 Accepted`**

```json
{
  "run_id": 1,
  "status": "PENDING"
}
```

이미 처리 완료된 동일 파일을 재요청하면 `status: "COMPLETED"`로 즉시 반환된다.

**Run Status**

| status | 설명 |
|--------|------|
| `PENDING` | 분석 대기 중 |
| `INGESTING` | 로그 파일 파싱 및 DB 적재 중 |
| `ANALYZING` | 정제, Trip 분리, 이벤트 탐지 중 |
| `COMPLETED` | 분석 완료 |
| `FAILED` | 분석 실패 (동일 파일 재요청 시 재시도) |
| `RECOVERING` | 서버 재시작 후 미완료 run 복구 처리 중 |

**Error Responses**

| Status | code | 설명 |
|--------|------|------|
| 400 | `MISSING_FILE` | 파일 미첨부 |
| 400 | `EMPTY_LOG_FILE` | 빈 파일 |
| 409 | `DUPLICATE_ANALYSIS` | 동일 파일이 현재 처리 중 |
| 413 | `PAYLOAD_TOO_LARGE` | 파일 크기 초과 (기본 200MB) |
| 422 | `INVALID_LOG_FORMAT` | JSON 파싱 불가 또는 최상위가 배열이 아님 |
| 503 | `DB_UNAVAILABLE` | DB 연결 실패 |

---

### GET /trips/{trip_id}

특정 Trip의 요약 정보와 탐지된 이벤트 목록을 반환한다.

**Response `200 OK`**

```json
{
  "trip_id": 1,
  "run_id": 1,
  "vehicle_id": "V001",
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-01T00:30:00Z",
  "duration_sec": 1800,
  "distance_m": 15230.5,
  "point_count": 1800,
  "event_counts": {
    "HARSH_ACCEL": 2,
    "HARSH_DECEL": 1,
    "SCHOOL_ZONE_SPEEDING": 3
  },
  "events": [
    {
      "event_id": 1,
      "type": "HARSH_ACCEL",
      "start_time": "2024-01-01T00:05:00Z",
      "end_time": "2024-01-01T00:05:03Z",
      "lat": 37.1234,
      "lon": 127.5678,
      "speed_kmh": null,
      "detail": { "max_change_kmh": 14.2 }
    },
    {
      "event_id": 4,
      "type": "SCHOOL_ZONE_SPEEDING",
      "start_time": "2024-01-01T00:12:00Z",
      "end_time": "2024-01-01T00:12:05Z",
      "lat": 37.2345,
      "lon": 127.6789,
      "speed_kmh": 42.1,
      "detail": { "max_speed_kmh": 42.1, "zones": "행복초등학교" }
    }
  ]
}
```

**Error Responses**

| Status | code | 설명 |
|--------|------|------|
| 404 | `TRIP_NOT_FOUND` | trip_id 없음 또는 분석이 아직 완료되지 않음 |

---

## 아키텍처

```
presentation/   라우터 (FastAPI)
    ↓
application/    유스케이스, 서비스, DTO
    ↓
domain/         순수 로직 (Polars 파이프라인, 이벤트 탐지)
infra/          DB, 파일 저장, JSON 파싱
core/           설정, 로깅, 미들웨어, 예외 핸들러
```

`domain/`은 FastAPI, SQLAlchemy 등 외부 프레임워크를 import하지 않는다. 계층 간 의존 방향은 import-linter로 강제한다.

### POST /analyze 처리 흐름

```
1. 파일 수신 (스트리밍)
2. SHA-256 해시 계산 → 중복 분석 여부 확인
3. analysis_runs 레코드 생성 (PENDING) → 즉시 202 반환
4. 백그라운드 스레드에서 2단계 처리:

   [1단계 - Ingestion]
   ijson 스트리밍 파싱 → 청크 단위 정규화
   → psycopg COPY로 raw_records 적재
   → 체크포인트(ingest_next_index: 마지막으로 적재한 레코드 위치) 갱신 (같은 트랜잭션)

   [2단계 - Analysis]
   커서 청크로 raw_records 읽기
   → 중복 병합 → Trip 분리 → 이상값 제거
   → 보간 → 이벤트 탐지 → Trip/Point/Event 저장
   → 체크포인트(analyze_last_vehicle/ts: 마지막으로 분석한 차량/시각) 갱신 (같은 트랜잭션)

5. analysis_runs 상태 → COMPLETED
```

---

## 요구사항 구현

### [Step 1] Data Cleansing & Ingestion

- **2단계 처리 (Ingestion → Analysis 분리)**: 파싱/적재 도중 서버가 종료되더라도 처음부터 다시 하지 않기 위해 단계를 분리했다. 각 단계에 체크포인트를 두어 재시작 시 이어서 처리한다.
- **정렬**: `ORDER BY vehicle_id, ts`로 정렬된 커서로 읽어 시간 순서를 보장한다.
- **이상값 제거**: 비현실적인 속도(`speed_max_kmh`: 최대 허용 속도 설정값 초과), 유효 범위를 벗어난 GPS 좌표를 null 처리한다. GPS 좌표 스왑(위경도 뒤집힘)은 자동으로 교정한다. 속도 스파이크와 GPS 순간이동은 전후 포인트와 비교해 제거한다.
- **결측값 보간**: null이 된 speed/lat/lon을 `interp_max_gap_sec`(최대 보간 허용 간격, 기본 10초) 이내에서 선형 보간한다. 연속 포인트 간 2~10초 공백에는 1초 단위 보간 행을 삽입해 연속성을 유지한다.

### [Step 2] Trip Segmentation

차량 변경 또는 5분 이상 공백이 발생하면 새 Trip으로 분리한다. Python 루프 없이 `cum_sum()`으로 trip_id를 벡터 연산으로 일괄 부여한다.

### [Step 3] Event Detection

- **급가속/급감속**: 1초 간격 연속 포인트에서 속도 변화량이 `harsh_kmh_per_sec`(급가속/급감속 판정 임계값, 기본 10km/h) 이상인 구간을 탐지한다. 연속 구간은 하나의 이벤트로 병합한다.
- **보호구역 과속**: 30km/h 초과 포인트를 먼저 필터링한 뒤 PostGIS `ST_DWithin`으로 반경 판정한다. Python에서 Haversine으로 전수 계산하면 포인트 × 보호구역 수만큼 연산이 발생하지만, PostGIS는 공간 인덱스를 타므로 대용량에서 훨씬 빠르다. 연속 과속 구간은 하나의 이벤트로 병합한다.

### [Step 4] API

- `POST /analyze`: 파일 수신 후 즉시 202 반환, 백그라운드에서 분석 처리
- `GET /trips/{trip_id}`: Trip 요약(주행 거리, 소요 시간) + 이벤트 목록 반환

---

## 추가로 고려한 설계

### 대용량 데이터 처리

**문제:** 수십만 건 이상의 로그를 메모리에 한 번에 올리면 OOM 위험.

**해결:**
- **스트리밍 파싱**: ijson(yajl2_c)으로 JSON 배열을 청크 단위로 읽는다. 파일 전체를 메모리에 올리지 않는다.
- **COPY 적재**: 청크를 PostgreSQL `COPY` 프로토콜로 직접 적재한다. ORM `add()` 반복 삽입 대비 대용량에서 훨씬 빠르다.
- **키셋 커서 기반 읽기**: 2단계 분석 시 `(vehicle_id, ts, source_index) > (마지막 차량, 마지막 시각, 마지막 레코드 번호)` 키셋 페이징으로 청크를 읽는다. OFFSET 방식은 뒤로 갈수록 느려지지만 키셋은 항상 인덱스를 탄다.
- **Polars 벡터 연산**: Python 행 단위 루프 없이 컬럼 연산과 `.over("trip_id")` window 함수로 처리한다. pandas 대비 메모리 효율과 속도가 높다.

### 중복 요청 방지

**문제:** 같은 파일을 여러 번 POST할 수 있다.

**해결:** SHA-256 해시 + zone_hash 복합 UNIQUE 제약으로 동일 (파일, 보호구역) 조합은 한 번만 처리한다. FAILED 상태의 run은 동일 파일 재요청 시 재사용(reset)된다.

### 서버 다운 / 재시작 복구

**문제:** 분석 도중 서버가 강제 종료되면 처리 중이던 run이 PENDING/INGESTING/ANALYZING 상태로 남는다.

**해결:**
- **체크포인트**: 청크마다 `ingest_next_index`(마지막으로 적재한 레코드 위치), `analyze_last_vehicle/ts`(마지막으로 분석한 차량/시각)를 데이터 저장과 같은 트랜잭션에 갱신한다. 트랜잭션이 원자적으로 커밋되므로 서버가 재시작되면 마지막 체크포인트부터 정확히 이어서 처리한다.
- **좀비 run 감지**: 서버 재시작 시 `updated_at` 기준 30분 이상 갱신되지 않은 run을 FAILED로 처리한 뒤 재시도한다.

### 다중 차량 로그

**문제:** 과제 명세는 단일 차량을 가정하지만, 실제 환경에서는 하나의 로그 파일에 여러 차량 데이터가 섞일 수 있다.

**해결:**
- raw_records를 `ORDER BY vehicle_id, ts`로 정렬해 커서 읽기. Trip 분리 기준에 차량 변경도 포함(`vehicle_id != 이전 vehicle_id` → 새 Trip).
- 로그에 vehicle_id 필드가 없는 경우 `?vehicle_id=` 쿼리 파라미터의 값을 기본값으로 사용한다.

### 이벤트 탐지 정확도

**문제:** 보간으로 채운 포인트를 실제 운전 데이터처럼 이벤트로 오인할 수 있다.

**해결:** `is_interpolated=True` 포인트는 급가속/급감속 탐지에서 제외한다. 센서가 실제로 측정하지 않은 구간은 이벤트로 판정하지 않는다.

### 멀티 인스턴스 / 동시성

**문제:** 여러 인스턴스가 동시에 같은 run을 처리하려 할 수 있다.

**해결:**
- `create_run`은 `SELECT FOR UPDATE`로 행 잠금 후 상태를 확인한다.
- 복구 시 `claim_incomplete_runs`는 `SELECT FOR UPDATE SKIP LOCKED`로 다른 인스턴스와 겹치지 않게 처리 대상을 가져온 뒤 즉시 RECOVERING으로 상태를 변경한다.

### 비정상 레코드 처리

**문제:** 배열 원소가 객체가 아닌 경우, 필수 필드 누락 등 다양한 불량 레코드가 존재한다.

**해결:** 거부된 레코드는 `rejected_records` 테이블에 원본 데이터와 거부 사유를 함께 저장한다. 처리를 중단하지 않고 나머지 유효 데이터를 계속 처리한다.

---

## 테스트

```
tests/
├── unit/               DB 없이 순수 로직만 테스트
│   ├── test_architecture.py    계층 의존 규칙, 금지 패턴 검사
│   ├── test_cleansing.py       스파이크, 텔레포트 제거
│   ├── test_events.py          급가속/급감속, 보호구역 과속 탐지
│   ├── test_geo.py             Haversine 거리 계산
│   ├── test_interpolation.py   값, 행 보간
│   ├── test_normalize.py       필드 정규화, 타입 변환
│   ├── test_segmentation.py    Trip 분리
│   └── test_zone.py            보호구역 로드, 좌표 범위 필터
└── integration/        Docker PostgreSQL 필요
    ├── test_analyze_api.py     POST /analyze E2E
    └── test_trips_api.py       GET /trips/{trip_id} E2E
```

```bash
# 단위 테스트
docker compose run --rm api pytest tests/unit

# 전체 테스트
docker compose run --rm api pytest
```
