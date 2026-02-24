# Reservation Manager

## 1) 프로젝트 목표와 필요성

### 목표
특정 자원(회의실, 테스트 단말기 등) 예약 시, 기존 예약과 시간이 겹치는지 자동으로 검증하여 **중복 예약을 차단**하는 시스템을 구현합니다.

### 필요성
수동 확인 방식에서는 시간 계산 실수로 중복 예약이 쉽게 발생할 수 있습니다.  
본 프로젝트는 시간 겹침 판별을 코드로 표준화해 사내 예약 업무의 정확도와 효율을 높입니다.

---

## 2) 핵심 로직

핵심은 두 시간 구간이 겹치는지 판별하는 함수입니다.

- 신규 예약: `(newStart, newEnd)`
- 기존 예약: `(existStart, existEnd)`

### 겹침 판별 수식

두 구간을 `[start, end)`(시작 포함, 종료 미포함)으로 해석하면,

```text
newStart < existEnd  AND  newEnd > existStart
```

를 만족할 때 두 구간은 겹칩니다.

### 경계값 처리 기준

- `10:00~11:00`과 `11:00~12:00`은 **겹치지 않음** (정확히 이어지는 예약 허용)
- 1분이라도 겹치면 **겹침으로 판단**

### 구현 위치

- 핵심 로직: `reservation_manager/booking.py`
  - `has_time_overlap(...)`
  - `can_reserve(...)`

### 자연어 예약 기능 (LLM 미사용)

규칙 기반(정규표현식) 파서를 사용해 자연어 입력에서 예약 정보를 추출합니다.

- Python: `reservation_manager/natural_language.py`
  - `parse_reservation_request(text)`
  - `can_reserve_from_text(text, existing_reservations)`
- Node.js: `nodejs/reservationParser.js`
  - `parseReservationRequest(text)`
  - `canReserveFromText(text, existingReservations)`

지원 예시 입력:

- `회의실A 2026-02-24 10:00~11:00 예약`
- `테스트 단말기 2026/02/24 14:30부터 15:30까지 예약해줘`

---

## 3) 테스트 코드

테스트 파일:

- `tests/test_booking.py`
- `tests/test_natural_language.py`

### 검증한 엣지 케이스

1. 기존 예약 시간의 앞/뒤로 완전히 벗어난 경우 → 통과
2. 기존 예약과 정확히 이어지는 경우 (`10:00~11:00` vs `11:00~12:00`) → 통과
3. 기존 예약과 일부 겹치는 경우 (`10:30~11:30`) → 실패
4. 기존 예약 내부에 완전히 포함되는 경우 → 실패

또한 복수 기존 예약에 대해 신규 예약 가능 여부를 판단하는 `can_reserve` 동작도 함께 검증합니다.

---

## 4) 실행 방법

### 요구 사항
- Python 3.9+

### 테스트 실행
프로젝트 루트(`reservation_manager`)에서 아래 명령을 실행하세요.

```bash
py -m unittest discover -s tests -v
```

Node.js 테스트는 아래 명령으로 실행합니다.

```bash
node --test nodejs/test/*.test.js
```

---

## 5) 프로젝트 구조

```text
reservation_manager/
├─ nodejs/
│  ├─ reservationParser.js
│  └─ test/
│     └─ reservationParser.test.js
├─ package.json
├─ reservation_manager/
│  ├─ __init__.py
│  ├─ booking.py
│  └─ natural_language.py
├─ tests/
│  ├─ test_booking.py
│  └─ test_natural_language.py
└─ README.md
```
