# Cloud Run deployment (PowerShell) for the FastAPI sales pipeline.
# Usage:  ./deploy_sales.ps1 -ProjectId my-proj -CloudSqlInstance my-proj:asia-south1:sales-db
param(
  [string]$ProjectId = "",
  [string]$Region = "asia-south1",
  [string]$Service = "kalisoft-sales",
  [string]$CloudSqlInstance = "",
  [string]$Bucket = "kalisoftai-datahub",
  [string]$ContactsPath = "all-sales-contacts-data",
  [string]$CorsOrigins = "*"
)

if (-not $ProjectId) { $ProjectId = (gcloud config get-value project) }
Write-Host "Project: $ProjectId  Region: $Region  Service: $Service"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com `
  secretmanager.googleapis.com sqladmin.googleapis.com storage.googleapis.com `
  --project $ProjectId

$sa = "kalisoft-sales-run@$ProjectId.iam.gserviceaccount.com"
gcloud iam service-accounts create kalisoft-sales-run `
  --display-name "Kalisoft Sales Cloud Run" --project $ProjectId 2>$null
gcloud storage buckets add-iam-policy-binding "gs://$Bucket" `
  --member="serviceAccount:$sa" --role="roles/storage.objectAdmin" 2>$null
gcloud projects add-iam-policy-binding $ProjectId `
  --member="serviceAccount:$sa" --role="roles/cloudsql.client" 2>$null

$dbUrl = Read-Host "SALES_DATABASE_URL (postgresql+psycopg2://user:pass@/db?host=/cloudsql/$CloudSqlInstance)"

gcloud builds submit --config cloudbuild.sales.yaml `
  --substitutions="_REGION=$Region,_CLOUD_SQL_INSTANCE=$CloudSqlInstance,_CORS_ORIGINS=$CorsOrigins" `
  --project $ProjectId

gcloud run services describe $Service --region $Region --format="value(status.url)"
