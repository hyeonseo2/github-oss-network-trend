# GitHub OSS Network Trend

[English](./README.md) | [한국어](./README.ko.md)

GitHub Pages 기반 정적 OSS 트렌드 대시보드입니다.

이 저장소는 더 이상 BigQuery, Cloud Run, dbt, Terraform을 사용하지 않습니다.
데이터는 GitHub Actions가 생성하고 정적 JSON으로 배포합니다.

## 1. 프로젝트 기능

- 7D/14D/30D 윈도우별 저장소 활동 변화 추적
- 저장소 간 공통 기여자 네트워크 엣지 생성
- 정적 파일 기반 UI(차트/테이블/네트워크) 제공

## 2. 현재 아키텍처

```text
GitHub REST API
    |
    v
GitHub Actions (스케줄 + 수동)
    |
    v
scripts/build_static_data.py
    |
    v
docs/data/*.json
    |
    v
GitHub Pages (docs/index.html)
```

## 3. 저장소 구조

```text
open-source-ecosystem-analytics-platform/
├── .github/workflows/pages.yml
├── scripts/build_static_data.py
├── docs/
│   ├── index.html
│   ├── data/
│   │   ├── meta.json
│   │   ├── trend_7d.json
│   │   ├── trend_14d.json
│   │   ├── trend_30d.json
│   │   ├── network_7d.json
│   │   ├── network_14d.json
│   │   ├── network_30d.json
│   │   └── top_repos.json
│   ├── github_pages_deploy.md
│   ├── operations_runbook.md
│   └── de_zoomcamp_project_document.md
├── .env.example
├── Makefile
└── README.md
```

## 4. 데이터 산출물

- `meta.json`: 빌드 메타데이터
- `trend_7d/14d/30d.json`: 윈도우별 트렌드 순위
- `network_7d/14d/30d.json`: 윈도우별 네트워크 노드/엣지
- `top_repos.json`: 상위 저장소 요약 스냅샷

## 5. 지표 정의

- `Activity Δ` = 현재 윈도우 이벤트 수 - 이전 윈도우 이벤트 수
- `Contributor Δ` = 현재 윈도우 고유 기여자 수 - 이전 윈도우 고유 기여자 수
- `Trend Score` = `Activity Δ + 2 * Contributor Δ`
- `shared_contributor_count` = 선택 윈도우에서 두 저장소 모두에 기여한 contributor 수

## 6. 로컬 실행

```bash
cp .env.example .env
source .env

make build-data
make run-site
```

로컬 URL: `http://127.0.0.1:8080`

## 7. GitHub Actions 데이터 갱신

워크플로우: `.github/workflows/pages.yml`

트리거:

- 매일 스케줄(UTC)
- 수동 실행(`workflow_dispatch`)
- `main` 브랜치에서 docs/script/workflow 변경 시

실행 단계:

1. GitHub API 호출
2. `docs/data/*.json` 재생성
3. `docs/`를 GitHub Pages에 배포

## 8. 설정 변수

`.env`(로컬) 또는 workflow env에서 설정:

- `GITHUB_TOKEN` (권장)
- `MAX_REPOS`
- `TREND_TOP_N`
- `NETWORK_MAX_EDGES`
- `MIN_SHARED_COUNT`
- `REQUEST_SLEEP_MS`
- `HTTP_TIMEOUT_SECONDS`
- `EVENT_MAX_PAGES`

## 9. 제약 사항

- 네트워크 품질은 GitHub API rate limit 및 이벤트 이력 범위에 영향받음
- 토큰 없이 실행하면 API 한도가 낮아 일부 저장소가 스킵될 수 있음
- 정적 스냅샷 방식이라 실시간 대시보드는 아님

## 10. 추가 문서

- [GitHub Pages 배포 가이드](docs/github_pages_deploy.md)
- [운영 런북](docs/operations_runbook.md)
- [DE Zoomcamp 프로젝트 문서](docs/de_zoomcamp_project_document.md)
