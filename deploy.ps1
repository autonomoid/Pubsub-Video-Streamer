# Set variables
$projectId = "racer-428819"
$imageName = "pubsub-video-streamer"
$region = "us-central1"
$cloudRunServiceName = "pubsub-video-streamer"
$subscription = "video-stream-test-sub"
$topic = "video-stream"

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

# Delete pubsub subscription
Write-Host "Deleting pubsub subscription..."
gcloud pubsub subscriptions delete $subscription
Check-LastCommand "Failed to delete pubsub subscription."

# Delete pubsub topic
Write-Host "Deleting pubsub topic..."
gcloud pubsub topics delete $topic
Check-LastCommand "Failed to delete pubsub topic."

# Create pubsub topic
Write-Host "Creating pubsub topic..."
gcloud pubsub topics create $topic
Check-LastCommand "Failed to create pubsub topic."

# Create pubsub subscription
Write-Host "Creating pubsub subscription..."
gcloud pubsub subscriptions create $subscription --topic=$topic
Check-LastCommand "Failed to create pubsub subscription."

Write-Host "Deployment completed successfully."