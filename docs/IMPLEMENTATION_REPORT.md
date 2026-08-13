# MVP 구현 보고서

## 구현됨

- 좌표 입력과 활성 XY/YZ/ZX/세 원자 평면 ray 교점 클릭으로 원자 생성
- 원자 클릭 시 정확한 좌표 표시, 좌표 수정 시 선택 원자 하나만 이동
- 단일·Ctrl/Shift 다중 선택, TransformControls 평행이동, undo/redo
- 거리·각도 HTML 라벨 클릭 편집, bridge 연결 성분 이동 및 고리 단일 원자 예외
- 공유결합 반지름·거리 기반 추론, 수동 결합/차수/삭제 exclusion
- JSON 저장/불러오기와 XYZ 입출력
- 전하·다중도 parity 검사, 두 ORCA 프리셋, capability 진단
- UUID 영속 단일 작업 큐, SSE, 취소, 재시작 interrupted 복구, 구조화 오류
- OPI 2.0 공개 API 기반 입력·파싱·MO/Cube 경계
- Cube 축/origin/단위 파싱, PyVista contour, PLY mesh와 hash cache
- total density/MO 독립 표면, ± 위상 색, opacity/isovalue, MO energy diagram
- H2O, CH4, F− 예제와 명시적 데모 계산 경로

## 환경 의존 검증

개발 환경에 OPI, ORCA, PyVista가 없으면 실제 ORCA 실행 및 orca_plot 출력은 검증되지 않는다. 이 경우 계산 버튼은 비활성화되고 원인 진단과 편집기는 계속 동작한다.

현재 검증 환경에는 `orca-pi==2.0.0`, ORCA 6.1.1, PyVista/VTK가 있다. 실제 ORCA 구조 최적화가 정상 종료하고 SCF·geometry 수렴, 7개 geometry, 최종 에너지 `-77.30256835801416 Eh`, restricted MO 48개를 OPI로 파싱했다. `orca_plot` Cube 생성의 실제 ORCA 통합 검증은 아직 남았다.

Windows CP949 로캘에서 ORCA의 UTF-8 em dash를 OPI grepper가 읽지 못하던 문제는 출력의 ASCII 수렴 마커를 바이트로 검사하도록 어댑터를 수정해 해결했다.

## 실행한 검증 (2026-08-13)

- `python -m pytest -q --basetemp test-artifacts/cp949-fix-full -p no:cacheprovider` → **25 passed**
- `python -m ruff check backend tests` → **All checks passed**
- `npm.cmd test` → **4 files, 14 tests passed**
- `npm.cmd run lint` → **0 errors**
- `npm.cmd run build` → **성공**, Vite 2,237 modules transformed. Three.js vendor를 포함한 500 kB 초과 chunk 경고는 남음.
- 로컬 브라우저 smoke: H2O 좌표 생성, 선택 원자 좌표 `[-0.24, 0.93, 0] → [-0.50, 0.93, 0]`, 데모 job `SUCCEEDED`, total density + HOMO surface 2개, console error 없음.

## 의도적으로 제외

반응 경로/TS/NEB/IRC, 분자동역학, 용매, 주기계, SMILES, conformer 전역 탐색, 계정·원격 계산은 구현하지 않았다.
