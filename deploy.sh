#!/usr/bin/env bash
#
# KalisoftAI Sales Agent - Google Cloud Run deployment
#
# Usage (from project root):
#   bash deploy.sh                       # uses default PROJECT_ID below
#   GOOGLE_CLOUD_PROJECT=other-project bash deploy.sh
#
# NOTE: this deploys the Django app (Dockerfile). The FastAPI sales pipeline
# (Dockerfile.sales / deploy_sales.sh) is a separate migration target that
# requires a Cloud SQL instance - do NOT use it for this deployment.
#
# Prerequisites:
#   - gcloud CLI installed & authenticated (gcloud auth login)
#   - cloudrun.env.yaml present in project root (copy from cloudrun.env.yaml.example
#     or upload your existing file; it is NOT in git because it is gitignored)
#   - credentials.json present in project root (auto-pushed to Secret Manager)
#
set -euo pipefail

DEFAULT_PROJECT_ID="${DEFAULT_PROJECT_ID:-gen-lang-client-0132243782}"
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "None" ]; then
  PROJECT_ID="$DEFAULT_PROJECT_ID"
fi

REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-sales-agent}"
AR_REPO="${AR_REPO:-cloud-run-source-deploy}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}"
ENV_FILE="${ENV_FILE:-cloudrun.env.yaml}"
SECRET_NAME="${SECRET_NAME:-google-app-credentials}"

echo "Project : $PROJECT_ID"
echo "Region  : $REGION"
echo "Service : $SERVICE_NAME"

# ---------------------------------------------------------------- preflight
command -v gcloud >/dev/null || { echo "ERROR: gcloud CLI not installed"; exit 1; }
[ -f "$ENV_FILE" ] || {
  echo "ERROR: $ENV_FILE not found."
  echo "       Copy cloudrun.env.yaml.example -> $ENV_FILE and fill real values."
  exit 1;
}

echo "=== Enabling required Google APIs (idempotent) ==="
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com storage.googleapis.com \
  sheets.googleapis.com drive.googleapis.com \
  --project "$PROJECT_ID" --quiet

# --------------------------------------------- service account -> Secret Mgr
if [ -f credentials.json ]; then
  echo "=== Pushing credentials.json to Secret Manager ($SECRET_NAME) ==="
  if gcloud secrets describe "$SECRET_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
    gcloud secrets versions add "$SECRET_NAME" --data-file=credentials.json \
      --project "$PROJECT_ID" --quiet
    echo "Secret updated (new version)"
  else
    gcloud secrets create "$SECRET_NAME" --data-file=credentials.json \
      --project "$PROJECT_ID" --quiet
    echo "Secret created"
  fi

  # Allow the Cloud Run runtime service account to read the secret
  PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
  RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
  gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
    --member="serviceAccount:$RUN_SA" \
    --role="roles/secretmanager.secretAccessor" \
    --project "$PROJECT_ID" --quiet >/dev/null
  echo "Runtime service account granted secret access"
elif gcloud secrets describe "$SECRET_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "=== Using existing Secret Manager secret ($SECRET_NAME) ==="
else
  echo "ERROR: credentials.json missing AND no existing secret '$SECRET_NAME'."
  exit 1
fi

# --------------------------------------------------- Artifact Registry repo
gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" \
  --project "$PROJECT_ID" >/dev/null 2>&1 || {
  echo "=== Creating Artifact Registry repository ($AR_REPO) ==="
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker --location="$REGION" --project "$PROJECT_ID" --quiet
}

# ------------------------------------------------------------------- build
echo "=== Building Docker image ==="
gcloud builds submit --tag "$IMAGE" --project "$PROJECT_ID"

# ------------------------------------------------------------------ deploy
echo "=== Deploying to Cloud Run ==="
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --platform managed \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 600 \
  --no-cpu-throttling \
  --env-vars-file "$ENV_FILE" \
  --set-secrets="GOOGLE_CREDENTIALS_JSON=${SECRET_NAME}:latest"

SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')"

echo ""
echo "=== Deployment complete ==="
echo "URL: $SERVICE_URL"
echo ""
echo "POST-DEPLOY CHECKLIST:"
echo "  1. Edit $ENV_FILE:"
echo "     CSRF_TRUSTED_ORIGINS=$SERVICE_URL"
echo "     SITE_URL=$SERVICE_URL   (password-reset email links use this)"
echo "     (ALLOWED_HOSTS can stay .run.app - it accepts all run.app domains)"
echo "  2. Re-run this script once so those values take effect."