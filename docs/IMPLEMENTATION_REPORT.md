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
- 기존 ORCA `*_MEP_trj.xyz`·`*_IRC_Full_trj.xyz` 자동 탐색, 검증, 원자적
  `reaction-path.json` 생성과 구조 경로 재생
- 별도 생성물 XYZ/GeoORCA 프로젝트 입력, endpoint 겹쳐 보기와 엄격한 원자 순서·전하·다중도 검증
- 반응 경로 전용 job에서 반응물/생성물 순차 `r2SCAN-3c OPT`, OPI 2.0 typed `BlockNeb` 기반
  IDPP 표준 NEB, 최종 `reaction_MEP_trj.xyz` 필수 검증과 manifest 자동 생성
- 단일 job의 `result.json`과 반응 경로 job의 `reaction-path.json` 분리, 성공 job 종류에 따른
  프런트엔드 결과 자동 로드
- H2O, CH4, F− 예제와 명시적 데모 계산 경로

## 환경 의존 검증

개발 환경에 OPI, ORCA, PyVista가 없으면 실제 ORCA 실행 및 orca_plot 출력은 검증되지 않는다. 이 경우 계산 버튼은 비활성화되고 원인 진단과 편집기는 계속 동작한다.

현재 검증 환경에는 `orca-pi==2.0.0`, ORCA 6.1.1, PyVista/VTK가 있다. 실제 ORCA 구조 최적화가 정상 종료하고 SCF·geometry 수렴, 7개 geometry, 최종 에너지 `-77.30256835801416 Eh`, restricted MO 48개를 OPI로 파싱했다. `orca_plot` Cube 생성의 실제 ORCA 통합 검증은 아직 남았다.

이번 반응 경로 변경은 설치된 OPI 2.0 typed API로 실제 `reaction.inp`를 생성해 `NEB`,
`BlockNeb`, IDPP, `NImages`, endpoint 파일, 전하와 다중도를 검증했다. 라이선스 ORCA를 사용하는
실제 NEB 계산은 기본 자동 테스트에서 실행하지 않고, 합성 ORCA 출력과 최종 MEP trajectory로
API부터 manifest 응답까지의 job 연결을 검증했다.

Windows CP949 로캘에서 ORCA의 UTF-8 em dash를 OPI grepper가 읽지 못하던 문제는 출력의 ASCII 수렴 마커를 바이트로 검사하도록 어댑터를 수정해 해결했다.

## 실행한 검증 (2026-08-14)

- `python -m pytest -q -p no:cacheprovider` → **95 passed, 1 deselected**
- `python -m ruff check backend tests` → **All checks passed**
- `npm.cmd test` → **12 files, 55 tests passed**
- `npm.cmd run lint` → **0 errors**
- `npm.cmd run build` → **성공**, Vite 2,251 modules transformed. Three.js/Plotly를 포함한 500 kB 초과 chunk 경고는 남음.
- 로컬 브라우저 smoke: H2O 좌표 생성, 선택 원자 좌표 `[-0.24, 0.93, 0] → [-0.50, 0.93, 0]`, 데모 job `SUCCEEDED`, total density + HOMO surface 2개, console error 없음.

## 의도적으로 제외

NEB-CI·NEB-TS·IRC 계산, 부분 IRC trajectory 자동 결합, `.interp.final` 에너지 보강,
이미지별 GBW·MO cube 자동 생성과 대응 추측은 구현하지 않았다. TS 계산, 분자동역학, 용매, 주기계, SMILES,
conformer 전역 탐색, 계정·원격 계산도 범위 밖이다.
