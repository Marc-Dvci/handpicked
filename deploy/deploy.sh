#!/usr/bin/env bash
# Build and deploy Handpicked to Cloud Run, with a keep-warm ping and a budget alert.
#
#   PROJECT=handpicked-xxxx REGION=europe-west1 BILLING=XXXXXX-XXXXXX-XXXXXX ./deploy/deploy.sh
#
# Secrets are read from the environment the first time (YOUCAM_API_KEY, DASHSCOPE_API_KEY) and stored in Secret
# Manager; they never enter the image or the repository. Every step can be re-run.
set -euo pipefail
: "${PROJECT:?set PROJECT}" "${REGION:=europe-west1}"
cd "$(dirname "$0")/.."
TAG=$(git rev-parse --short HEAD)
IMAGE="$REGION-docker.pkg.dev/$PROJECT/handpicked/app:$TAG"

gcloud config set project "$PROJECT" >/dev/null
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com billingbudgets.googleapis.com

gcloud artifacts repositories describe handpicked --location "$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create handpicked --repository-format docker --location "$REGION"

for pair in "youcam-api-key:YOUCAM_API_KEY" "dashscope-api-key:DASHSCOPE_API_KEY"; do
  name=${pair%%:*}; var=${pair##*:}
  if ! gcloud secrets describe "$name" >/dev/null 2>&1; then
    gcloud secrets create "$name" --replication-policy automatic
    printf %s "${!var:?set $var for the first deploy}" | gcloud secrets versions add "$name" --data-file=-
  fi
done
NUMBER=$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')
for name in youcam-api-key dashscope-api-key; do
  gcloud secrets add-iam-policy-binding "$name" --role roles/secretmanager.secretAccessor \
    --member "serviceAccount:$NUMBER-compute@developer.gserviceaccount.com" >/dev/null
done

gcloud builds submit --tag "$IMAGE" .
sed "s#IMAGE#$IMAGE#" deploy/service.yaml > /tmp/handpicked-service.yaml
gcloud run services replace /tmp/handpicked-service.yaml --region "$REGION"
gcloud run services add-iam-policy-binding handpicked --region "$REGION" --member allUsers --role roles/run.invoker >/dev/null
URL=$(gcloud run services describe handpicked --region "$REGION" --format 'value(status.url)')

# keep one instance warm through judging: a health ping every 10 minutes (Cloud Scheduler free tier)
gcloud scheduler jobs describe handpicked-warm --location "$REGION" >/dev/null 2>&1 || \
  gcloud scheduler jobs create http handpicked-warm --location "$REGION" --schedule "*/10 * * * *" \
    --uri "$URL/api/health" --http-method GET

# budget alert on gross spend (credits excluded), so it fires before any money is charged
if [ -n "${BILLING:-}" ] && ! gcloud billing budgets list --billing-account "$BILLING" --format 'value(displayName)' | grep -qx handpicked; then
  gcloud billing budgets create --billing-account "$BILLING" --display-name handpicked \
    --budget-amount 10EUR --filter-projects "projects/$PROJECT" --credit-types-treatment EXCLUDE_ALL_CREDITS \
    --threshold-rule percent=0.5 --threshold-rule percent=0.9 --threshold-rule percent=1.0
fi
echo "$URL"
