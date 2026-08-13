# 구조와 경계

GeoORCA MVP는 브라우저 편집기와 `127.0.0.1` 전용 FastAPI 서버로 나뉜다. 브라우저의 직렬화 가능한 `MoleculeProject`가 사용자의 원본이며, 계산을 시작할 때 UUID 작업 폴더에 스냅샷과 원자 UUID↔ORCA 0-based index 대응표를 저장한다.

```text
React/Zustand ──REST/SSE── FastAPI ── JobManager(1 worker)
     │                         ├── OpiAdapter ── ORCA 6.1.1+
 React Three Fiber            └── Cube parser ── PyVista/VTK ── PLY mesh
```

## 중요한 경계

- UI 결합은 편집·표시용 추정 그래프다. ORCA에 Lewis 결합표로 전달하지 않는다.
- 모든 프로젝트/API 좌표는 Å이다. Cube parser가 Bohr를 Å로 변환하는 유일한 체적 좌표 단위 경계다.
- OPI import와 공개 API 사용은 `backend/app/chemistry/opi_adapter.py` 및 surface 생성에 격리된다.
- 원시 Cube scalar 배열은 브라우저로 전송하지 않는다. 서버가 contour를 PLY mesh로 추출한다.
- opacity는 렌더 속성이므로 surface cache key에서 제외한다.
- 클라이언트가 시스템 경로나 작업 폴더명을 고르지 않는다. 작업과 mesh 파일명은 서버 UUID/hash만 사용한다.

## 편집 규칙

정확한 좌표 패널 편집은 선택한 원자 하나만 이동한다. 길이·각도 도구만 명시적인 graph 규칙에 따라 bridge 반대편 연결 성분을 함께 움직인다. 고리 edge 또는 직접 결합이 아닌 측정에서는 늦게 선택한 원자 하나만 움직인다. 모든 초기 구조 편집은 100단계 snapshot undo/redo를 사용한다. 계산 결과는 초기 구조와 별도 snapshot으로 보존된다.

