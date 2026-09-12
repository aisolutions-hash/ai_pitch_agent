# Cloud Run deployment helpers for the FastAPI sales pipeline.
# Usage:  bash deploy_sales.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project)}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-kalisoft-sales}"
INSTANCE_CONNECTION_NAME="${INSTANCE_CONNECTION_NAME:-}"
BUCKET="${GCS_BUCKET_CONTACTS:-kalisoftai-datahub}"
CONTACTS_PATH="${GCS_PATH_CONTACTS:-all-sales-contacts-data}"

echo "Project : $PROJECT_ID"
echo "Region  : $REGION"
echo "Service : $SERVICE"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com sqladmin.googleapis.com storage.googleapis.com \
  --project "$PROJECT_ID"

# 1) Runtime service account (ADC on Cloud Run)
SA="kalisoft-sales-run@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts create kalisoft-sales-run \
  --display-name "Kalisoft Sales Cloud Run" --project "$PROJECT_ID" || true

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SA}" --role="roles/storage.objectAdmin" || true
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" --role="roles/cloudsql.client" || true

# 2) Secrets
echo -n "$(openssl rand -hex 32)" | gcloud secrets create SALES_SECRET_KEY \
  --data-file=- --project "$PROJECT_ID" || \
  echo -n "$(openssl rand -hex 32)" | gcloud secrets versions add SALES_SECRET_KEY \
  --data-file=- --project "$PROJECT_ID"

read -r -p "SALES_DATABASE_URL (postgresql+psycopg2://user:pass@/db?host=/cloudsql/$INSTANCE_CONNECTION_NAME): " DB_URL
echo -n "$DB_URL" | gcloud secrets create SALES_DATABASE_URL \
  --data-file=- --project "$PROJECT_ID" || \
  echo -n "$DB_URL" | gcloud secrets versions add SALES_DATABASE_URL \
  --data-file=- --project "$PROJECT_ID"

# 3) Build & deploy
gcloud builds submit --config cloudbuild.sales.yaml \
  --substitutions="_REGION=${REGION},_CLOUD_SQL_INSTANCE=${INSTANCE_CONNECTION_NAME}" \
  --project "$PROJECT_ID"

echo "Deployed. Fetch URL with:"
echo "  gcloud run services describe ${SERVICE} --region ${REGION} --format='value(status.url)'"
