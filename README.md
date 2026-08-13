# GeoORCA MVP

좌표에서 시작하는 3D 분자 편집기와 로컬 ORCA 구조 최적화·전자구조 시각화 도구다. 브라우저에서 원자를 배치하고 길이/각도를 편집한 뒤 OPI 2.0을 통해 ORCA 6.1.1+ 계산을 실행한다. 큰 Gaussian Cube는 서버에서 PyVista/VTK 등밀도면으로 바꾸고 PLY mesh만 브라우저에 보낸다.

> 이 앱은 전역적으로 가장 안정한 구조를 찾지 않는다. 결과는 **입력 구조에서 찾은 국소 최적화 구조**다.

반응 경로, NEB/IRC/전이상태, 분자동역학, 용매, 주기계, SMILES 구조 생성, conformer 전역 탐색은 이 MVP의 범위가 아니다.

## 화면에서 할 수 있는 일

- 정확한 `x/y/z` 또는 활성 XY/YZ/ZX/세 원자 평면 클릭으로 원자 추가
- 원자 클릭 후 좌표 수정: 선택한 원자 하나만 이동
- 선택·Ctrl/Shift 다중 선택과 이동 gizmo, undo/redo
- 클릭 가능한 Å/° 라벨로 길이와 각도 수정
- 거리 기반 결합 추론, 수동 추가·삭제·차수와 삭제 override
- 프로젝트 JSON 및 XYZ 저장/불러오기
- 전하, 다중도, 빠른 미리보기/표준 프리셋
- 초기 구조와 최적 구조, total density, 선택 MO ± 위상 표면
- MO 에너지(eV/Eh), HOMO/LUMO, 총에너지, 수렴 상태, 로그

## 구조

```text
frontend/                  Vite + React + TypeScript + React Three Fiber + Zustand
backend/app/api/           FastAPI REST/SSE
backend/app/chemistry/     capability, preset, OPI 2.0 adapter
backend/app/jobs/          UUID 영속 작업 큐·취소·복구
backend/app/surfaces/      Cube parser, PyVista contour, PLY cache
examples/                  H2O, CH4, F−
tests/                     pytest
docs/                      설계·계산 의미·구현 보고서
```

자세한 경계는 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), 계산 해석은 [docs/CHEMISTRY.md](docs/CHEMISTRY.md), 구현 범위는 [docs/IMPLEMENTATION_REPORT.md](docs/IMPLEMENTATION_REPORT.md)에 있다.

## Windows 설치

필수 환경은 Python 3.11–3.13, Node.js 20+, npm이다. ORCA 계산을 쓰려면 FACCTs에서 ORCA를 별도로 설치하고 라이선스를 확인해야 한다. ORCA 바이너리는 저장소에 포함하거나 자동 다운로드하지 않는다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Set-Location frontend
npm.cmd install
Set-Location ..
```

`orca-pi==2.0.0`을 고정한다. OPI 2.0은 ORCA 6.1.1 이상을 요구한다. ORCA 경로는 `.env.example`을 참고해 환경 변수로 지정한다.

```powershell
$env:GEOORCA_ORCA_PATH = 'C:\Program Files\ORCA_6.1.1\orca.exe'
```

또는 서버가 실행 중일 때 다음 로컬 API로 저장할 수 있다. 경로는 `data/settings.json`에만 기록된다.

```powershell
Invoke-RestMethod -Method Put -Uri http://127.0.0.1:8000/api/settings/orca-path `
  -ContentType application/json -Body '{"path":"C:\\Program Files\\ORCA_6.1.1\\orca.exe"}'
```

## 실행

한 명령으로 백엔드와 프론트엔드를 실행한다. 서버는 모두 loopback에만 bind한다.

```powershell
.\scripts\dev.ps1
```

브라우저에서 `http://127.0.0.1:5173`을 연다. 개별 실행은 다음과 같다.

```powershell
python -X utf8 -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
Set-Location frontend; npm.cmd run dev
```

ORCA/OPI가 없거나 버전이 맞지 않아도 편집, 저장, 측정은 동작한다. 실제 ORCA 버튼은 비활성화되고 원인이 속성 패널에 표시된다. `GEOORCA_DEMO_CALCULATIONS=1`이면 “데모 결과”로 계산 후 UI 흐름을 시험할 수 있지만 이는 실제 양자화학 결과가 아니다.

## 사용 흐름

1. `examples/h2o.geoorca.json`을 연다.
2. 원자 구를 클릭하면 오른쪽에 정확한 좌표가 나타난다. 한 좌표를 수정하면 그 원자만 이동한다.
3. 원소 추가에서 원소를 고르고 좌표로 만들거나 활성 평면을 클릭한다.
4. 길이 도구는 A→B, 각도 도구는 A→B(꼭짓점)→C 순서로 고른 뒤 라벨을 클릭한다.
5. 전하·다중도와 프리셋을 확인하고 ORCA 계산 또는 명시적 데모 결과를 실행한다.
6. 계산 후 density/MO 표면과 에너지 도표를 사용한다.

XYZ에는 결합 정보가 없으므로 import 후 결합을 다시 추론한다. 자동 결합은 화학적 확정이 아니라 UI용 추정이다.

## 계산 프리셋

- 빠른 미리보기: `R2SCAN-3C OPT`; 작은 분자의 낮은 비용 국소 최적화.
- 표준: `R2SCAN-3C OPT` 후 최적 좌표에서 `PBE0 D4 DEF2-SVP TIGHTSCF SP` 전자구조 계산.

전체 전자 밀도와 MO는 서로 다른 field다. MO의 양/음 색은 확률의 양/음이 아니라 파동함수의 위상이다. opacity는 브라우저 속성이어서 mesh를 다시 만들지 않고, isovalue는 300 ms debounce 뒤 같은 Cube에서 contour만 다시 만든다.

## 계산된 반응 경로 재생

계산 설정의 `계산 종류`에서 `반응 경로`를 선택하면 현재 작업 폴더에서 최종 ORCA NEB
`*_MEP_trj.xyz` 또는 양방향 IRC `*_IRC_Full_trj.xyz`를 찾는다. manifest가 없으면 같은 작업
폴더의 `data/jobs/<UUID>/reaction-path.json`으로 자동 생성한다. `*_MEP_ALL_trj.xyz`와 부분 IRC
trajectory는 최종 경로로 추측하지 않는다. 이 모드는 새로운 NEB·IRC 계산을 실행하지 않으며,
표시 프레임은 실제 시간 trajectory가 아니다.

자동 manifest는 UTF-8 JSON이며 `schemaVersion: 1`, `sourceType`, `sourceTrajectory`,
`energyReference: first-image`, `energyUnit: hartree`, `relativeEnergyUnit: kJ/mol`, 원본 파일의
크기·수정 시각·SHA-256과 실제 계산 이미지들을 기록한다. 명시적인 ORCA 에너지 표기가 없는
이미지의 에너지는 `null`이며 보간해 저장하지 않는다. 원본 fingerprint나 schema가 달라지면
지연 조회 시 원자적으로 재생성한다. 기존 version 1 수동 manifest의 eV·kJ/mol 입력 호환성도
유지한다.

`wavefunctionRef`와 `orbitalRefs`는 작업 디렉터리 기준의 존재하는 상대 경로만 허용하며 절대 경로,
`..`, symlink를 통한 이탈을 거부한다. trajectory만으로 이미지별 GBW 대응을 추측하지 않으므로
자동 생성 경로의 `wavefunctionRef`는 `null`이다. 이 경우에도 구조 경로는 정상 재생하고 MO
컨트롤만 비활성화한다. 작은 수동 manifest 예시는 [테스트 fixture](tests/fixtures/reaction-path.json)에 있다.

백엔드는 첫 계산 지점을 기준으로 질량 가중 Kabsch 정렬을 하고, 단조 반응좌표 또는 정렬 좌표의
누적 길이를 0..1로 정규화한다. 표시 좌표는 구간별 cubic Hermite로 만들며 두 지점뿐인 경로,
불안정한 접선·급격한 방향 반전, 과도한 overshoot, 새 원자 겹침, 비유한 결과에서는 해당 구간을
선형 보간한다. 기본 구간 샘플 수는 `backend/app/reaction_path/geometry.py`의 한 상수로 관리한다.

선택한 MO만 같은 spin의 ±5 후보에서 공통 cube 격자 signed overlap으로 추적한다. 절댓값 중첩이
0.60 미만이면 branch를 영구 종료하고, 음의 signed overlap이면 다음 표시 field의 위상을 뒤집는다.
위상 정렬한 scalar field를 먼저 보간한 뒤 각 표시 프레임의 등치면을 작업 디렉터리에 지연 생성한다.
원본 cube는 수정하거나 삭제하지 않는다. 준축퇴 오비탈은 현재 단일 오비탈 배정만 사용하므로
후속 부분공간 추적 확장 지점으로 남아 있다.

## 테스트와 검사

```powershell
python -m pytest -q
python -m ruff check backend tests
Set-Location frontend
npm.cmd test
npm.cmd run lint
npm.cmd run build
```

실제 ORCA 테스트는 기본 suite에서 제외하며 설치된 개발 환경에서만 실행한다.

```powershell
python -m pytest -m orca
```

프로젝트 원본 JSON은 브라우저에서 사용자가 저장한다. 계산 작업은 기본적으로 `data/jobs/<UUID>/`에 `project.json`, `job.json`, OPI/ORCA 입력·출력, Cube, mesh, `result.json`을 보존한다. 서버가 재시작되면 RUNNING/QUEUED 작업은 성공으로 간주하지 않고 `INTERRUPTED` 실패로 복구한다.

## 문제 해결

- Windows에서 `'cp949' codec can't decode byte 0xe2` 오류가 나더라도 ORCA 계산 자체가 실패했다는 뜻은 아닙니다. ORCA 6.1 출력의 UTF-8 문장부호와 Windows CP949 로캘이 충돌할 수 있으며, 현재 어댑터는 정상 종료·SCF·geometry 수렴 마커를 바이트로 검사해 이 문제를 회피합니다.
  이전 백엔드가 실행 중이었다면 터미널에서 종료한 뒤 `\.\scripts\dev.ps1`로 다시 시작해야 수정된 모듈이 로드됩니다.

- ORCA 미탐지: `GEOORCA_ORCA_PATH`가 실제 `orca.exe`를 가리키는지 `/api/capabilities`에서 확인한다.
- 버전 불일치: OPI 2.0에는 ORCA 6.1.1 이상이 필요하다.
- SCF/geometry 미수렴: 초기 구조, 전하, 다중도, 방법 적합성을 확인한다. 앱이 임의로 전하나 스핀을 바꾸지 않는다.
- Cube 실패: `orca_plot` 탐지, GBW 보존 여부, 작업 로그를 확인한다. 빈 isovalue에서는 값을 낮춘다.
- 투명 표면 artefact: 여러 DoubleSide 투명 mesh의 WebGL depth sorting 한계다. 동시 표면 수나 opacity를 줄인다.
- 새로고침: 마지막 job UUID는 프로젝트의 `lastCalculationId`와 작업 폴더로 재조회할 수 있다. 작업 산출물은 지워지지 않는다.

## 검증 상태

현재 환경에서 실행한 명령과 결과, 실제 ORCA 환경에서만 남는 검증은 [구현 보고서](docs/IMPLEMENTATION_REPORT.md)에 기록한다. GitHub push는 수행하지 않았다.
