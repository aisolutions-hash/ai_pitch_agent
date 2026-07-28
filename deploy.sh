#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-your-project-id}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-sales-agent}"
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

echo "=== Building Docker image ==="
gcloud builds submit --tag "$IMAGE_NAME" --project "$PROJECT_ID"

echo "=== Deploying to Cloud Run ==="
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE_NAME" \
  --platform managed \
  --region "$REGION" \
  --allow-unauthenticated \
  --project "$PROJECT_ID" \
  --env-vars-file cloudrun.env

echo "=== Deployment complete ==="
echo "Service URL: https://$SERVICE_NAME-$(echo $PROJECT_ID | tr ':' '-').$REGION.run.app"
