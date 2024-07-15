# Set variables
$projectId = "racer-428819"
$imageName = "pubsub-video-streamer"
$region = "us-central1"
$cloudRunServiceName = "pubsub-video-streamer"

# Function to check last command status and exit if failed
function Check-LastCommand {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: $($args[0])"
        exit $LASTEXITCODE
    }
}

# Rebuild the Docker image
Write-Host "Rebuilding the Docker image..."
docker build -t "gcr.io/$projectId/$imageName" .
Check-LastCommand "Failed to build the Docker image."

# Push the Docker image to GCR
Write-Host "Pushing the Docker image to GCR..."
docker push "gcr.io/$projectId/$imageName"
Check-LastCommand "Failed to push the Docker image."

# Deploy the new image to Cloud Run
Write-Host "Deploying the new image to Cloud Run..."
gcloud run deploy $cloudRunServiceName `
  --image "gcr.io/$projectId/$imageName" `
  --platform managed `
  --region $region `
  --allow-unauthenticated `
  --memory 1Gi
Check-LastCommand "Failed to deploy to Cloud Run."

Write-Host "Deployment completed successfully."