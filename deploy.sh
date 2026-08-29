#!/usr/bin/env bash
#
# KalisoftAI Sales Agent - Google Cloud Run deployment
#
# Usage (from project root):
#   GOOGLE_CLOUD_PROJECT=my-project-id bash deploy.sh
#
# Prerequisites:
#   - gcloud CLI installed & authenticated (gcloud auth login)
#   - cloudrun.env.yaml present (copy from cloudrun.env.yaml.example, fill values)
#   - credentials.json present (auto-pushed to Secret Manager)
#
set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
[ -n "$PROJECT_ID" ] && [ "$PROJECT_ID" != "None" ] || {
  echo "ERROR: Set GOOGLE_CLOUD_PROJECT or run 'gcloud config set project <id>'"; exit 1;
}

REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-sales-agent}"
AR_REPO="${AR_REPO:-cloud-run-source-deploy}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}"
ENV_FILE="${ENV_FILE:-cloudrun.env.yaml}"
SECRET_NAME="${SECRET_NAME:-google-app-credentials}"

# ---------------------------------------------------- env-to-yaml converter
# Converts plain KEY=value .env format to YAML for gcloud --env-vars-file
env_to_yaml() {
  local src="$1" dst
  dst=$(mktemp)
  while IFS= read -r line || [ -n "$line" ]; do
    # skip comments and blank lines
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    # strip leading whitespace, split on first =
    key="${line%%=\"*}"
    key="${key%%\'*)}"
    key="${key#"${key%%[![:space:]]*}"}"  # trim leading spaces
    [ -z "$key" ] && continue
    val="${line#*=}"
    # remove surrounding quotes if present
    val="${val%\"}"
    val="${val\'})}"
    val="${val#\"}"
    val="${val#\'}"
    # escape YAML special chars
    val=$(printf '%s' "$val" | sed 's/"/\\"/g')
    printf '%s: %s\n' "$key" "$val" >> "$dst"
  done < "$src"
  printf '%s\n' "$dst"
}

# ---------------------------------------------------- convert .env to YAML if needed
if [[ "$ENV_FILE" == *.env && ! "$ENV_FILE" == *.yaml && ! "$ENV_FILE" == *.yml ]]; then
  echo "=== Converting .env to YAML format ==="
  ENV_FILE=$(env_to_yaml "$ENV_FILE")
  if [ ! -s "$ENV_FILE" ]; then
    echo "ERROR: Converted YAML is empty. Check your .env file format."
    exit 1
  fi
fi

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