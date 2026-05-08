# GitHub OSS Network Trend (정적 버전)

[English](./README.md) | [한국어](./README.ko.md)

이 프로젝트는 GitHub Pages에 배포되는 정적 대시보드로 전환되었습니다.
이제 BigQuery, Cloud Run, dbt, Terraform을 사용하지 않습니다.

## 개요

- 데이터 소스: GitHub REST API
- 배치 실행: GitHub Actions (일 1회)
- 산출물: `docs/data/*.json`
- 호스팅: GitHub Pages

## 아키텍처

```text
GitHub API
   |
   v
GitHub Actions (스케줄 실행)
   |
   v
scripts/build_static_data.py
   |
   v
docs/data/*.json
   |
   v
GitHub Pages (docs/)
```

## 빠른 시작

1. 환경 변수를 설정합니다.
2. 정적 데이터를 생성합니다.
3. 로컬에서 정적 사이트를 실행합니다.

```bash
cp .env.example .env
source .env

make build-data
make run-site
```

브라우저에서 `http://127.0.0.1:8080` 접속.

## GitHub Pages 배포

저장소에 Pages 배포 워크플로우가 포함되어 있습니다.

- [pages.yml](.github/workflows/pages.yml)

워크플로우 동작:

1. 매일(UTC) 및 수동 실행
2. `docs/data`에 최신 JSON 스냅샷 생성
3. `docs/` 디렉터리를 GitHub Pages로 배포

설정 가이드:

- [GitHub Pages 배포 가이드](docs/github_pages_deploy.md)

## 생성 데이터 파일

- `docs/data/meta.json`
- `docs/data/trend_7d.json`
- `docs/data/trend_14d.json`
- `docs/data/trend_30d.json`
- `docs/data/network_7d.json`
- `docs/data/network_14d.json`
- `docs/data/network_30d.json`
- `docs/data/top_repos.json`

## 전환 후 비용 구조

- BigQuery: 제거
- Cloud Run: 제거
- GCP 인프라: 제거
- 잔여 비용: GitHub Actions 사용량, GitHub Pages 트래픽

공개 저장소라면 GitHub 정책상 표준 러너 사용은 무료 범위에서 운영 가능합니다.
