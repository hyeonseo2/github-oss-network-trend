# GitHub OSS Network Trend

[English](./README.md) | [한국어](./README.ko.md)

이 프로젝트는 GitHub 공개 이벤트 데이터를 기반으로 저장소 성장 추세와 저장소 간 협업 연결망을 분석하는 엔드투엔드 데이터 파이프라인입니다.

GitHub Actions로 매일 배치를 수행하고, dbt로 BigQuery에서 분석 마트를 구성해 Cloud Run의 Flask 대시보드로 제공합니다.

## 1. 개요

- 공개 GitHub 이벤트(푸시/PR/Issue 기반)로 성장성 지표를 계산
- 저장소 간 중복 기여자 네트워크를 생성해 연결성을 분석
- Trend / Network 뷰를 한 화면에서 확인

### 이벤트 기반 지표

- **Activity Δ**: 현재 기간 이벤트 합계 - 이전 기간 이벤트 합계
- **Contributor Δ**: 현재 기간 고유 기여자 수 - 이전 기간 고유 기여자 수
- **Event Stars (window)**: 선택 기간 이벤트 수(표기용)
- **Active Contributors (window)**: 선택 기간 고유 기여자 수(표기용)

## 2. 아키텍처

```text
GitHub Archive (공개 이벤트)
        |
        v
GitHub Actions (일일 배치)
        |
        v
GCS raw zone + BigQuery raw 테이블(파티션/클러스터)
        |
        v
dbt (staging -> intermediate -> marts)
        |
        v
BigQuery marts
  - mart_repo_trend
  - mart_contributor_edges
  - mart_repo_popularity_snapshots
        |
        v
Cloud Run Flask 대시보드
```

## 3. 폴더 구성

```text
open-source-ecosystem-analytics-platform/
├── app/                  # Flask 앱 및 템플릿
├── dbt/                  # 스테이징/중간/마트 SQL 모델
├── docs/                 # 문서
├── terraform/            # 인프라 IaC
├── .github/workflows/    # 배치 파이프라인
├── .env.example
├── requirements-web.txt
├── Makefile
└── README.md
```

## 4. 실행 전 준비

- BigQuery, Cloud Run이 활성화된 GCP 프로젝트
- GitHub Actions 사용 가능한 GitHub 저장소
- Terraform, `gcloud`, Python 3.10+, `make`
- `dbt-core`, `dbt-bigquery`

## 5. 빠른 시작

### 5.1 환경 변수 설정

```bash
cp .env.example .env
# 값 채우기
source .env
```

### 5.2 인프라 배포

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

### 5.3 로컬에서 dbt 실행

```bash
cd dbt
cp profiles.yml.example profiles.yml

dbt debug --profiles-dir . --target prod

dbt run --profiles-dir . --target prod \
  --vars '{"gcp_project_id":"'$GCP_PROJECT_ID'","raw_dataset":"oss_analytics_raw","raw_table":"raw_github_events","analysis_window_days":30,"network_window_days":30,"min_daily_events_for_trend":5}'

dbt test --profiles-dir . --target prod \
  --vars '{"gcp_project_id":"'$GCP_PROJECT_ID'","raw_dataset":"oss_analytics_raw","raw_table":"raw_github_events"}'
```

### 5.4 대시보드 실행

```bash
# 로컬
make run-dashboard

# Cloud Run 배포

gcloud run deploy oss-analytics-dashboard \
  --source . \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated
```

## 6. 파이프라인 동작

`.github/workflows/oss-batch-pipeline.yml`

1. 대상 날짜 결정(수동 입력 가능, 기본값은 전날)
2. GCP 인증(OIDC 우선)
3. raw 테이블 보장(파티션/클러스터)
4. `githubarchive` export → GCS → BigQuery 적재
5. `dbt run`
6. `dbt test`
7. 품질 검증 SQL 실행
8. 실행 이력(`pipeline_runs`) 저장

## 7. 대시보드 동작

- 기본 필터: **30일 + 네트워크 ON**
- Trend는 Activity/Contributor 변화량 기반으로 정렬
- Network는 공통 기여자 기반 엣지로 노드 간 관계 표시
- UI에서 파이프라인을 직접 실행하지 않고 조회 전용

## 8. 데이터 모델 요약

- `stg_github_events`, `int_repo_daily_activity`
- `mart_repo_trend`, `mart_contributor_edges`
- `mart_repo_popularity_snapshots`, `pipeline_runs`

## 9. 운영 참고

- workflow_dispatch의 `target_date`, `backfill_days`로 재실행
- `skip_quality_gate=1`은 임시 회피용(주의)
- 네트워크 계산량은 `network_window_days`, `min_shared_repo_count`로 조절

## 10. 문서 링크

- [Cloud Run 배포 가이드](docs/cloud_run_deploy.md)
- [DE Zoomcamp 프로젝트 문서](docs/de_zoomcamp_project_document.md)