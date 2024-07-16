import cv2
from google.cloud import storage, pubsub_v1, tasks_v2
import base64
import io
import time
import logging
from flask import Flask, request, jsonify
import json
import hashlib
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# Load configuration from config.json
with open('config.json') as config_file:
    config = json.load(config_file)

CLOUD_RUN_URL = config['CLOUD_RUN_URL']
BUCKET_NAME = config['BUCKET_NAME']
VIDEO_PATH = config['VIDEO_PATH']
PROJECT_ID = config['PROJECT_ID']
TOPIC_NAME = config['TOPIC_NAME']
SUBSCRIPTION_NAME = config['SUBSCRIPTION_NAME']
QUEUE_NAME = config['QUEUE_NAME']
LOCATION = 'us-central1'  # Set this to your queue's location

def get_video_stream_from_gcs(bucket_name, video_path):
    """Streams video data directly from GCS."""
    logging.debug(f"Streaming video from bucket {bucket_name}, path {video_path}")
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(video_path)
    video_stream = io.BytesIO()
    blob.download_to_file(video_stream)
    video_stream.seek(0)  # Rewind the stream to the beginning
    return video_stream

def publish_frames_to_pubsub(video_stream, project_id, topic_name):
    """Extracts frames from the video stream and publishes them to a Pub/Sub topic at the natural frame rate."""
    logging.debug(f"Publishing frames to Pub/Sub topic {topic_name} in project {project_id}")

    # Configure the publisher with message ordering enabled
    publisher_options = pubsub_v1.types.PublisherOptions(enable_message_ordering=True)
    client_options = {"api_endpoint": "us-east1-pubsub.googleapis.com:443"}  # Adjust the region as needed
    publisher = pubsub_v1.PublisherClient(publisher_options=publisher_options, client_options=client_options)
    topic_path = str(publisher.topic_path(project_id, topic_name))

    # Use OpenCV to read the video stream
    video_stream.seek(0)  # Ensure the stream is at the beginning
    cap = cv2.VideoCapture(video_stream)

    frame_rate = cap.get(cv2.CAP_PROP_FPS)
    frame_delay = 1.0 / frame_rate

    frame_id = 0
    ordering_key = "video-stream"  # Set a fixed ordering key to maintain order
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # Compress the frame to JPEG format with quality 75 (adjust as needed)
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 75]
        _, buffer = cv2.imencode('.jpg', frame, encode_param)
        data = base64.b64encode(buffer).decode('utf-8')  # Ensure frame_bytes is a string
  
        logging.debug(f"Published frame {frame_id} with frame rate {frame_rate}")
        logging.debug(f"Topic path: {topic_path}")
        logging.debug(f"Ordering key: {ordering_key}")
        
        future = publisher.publish(
            topic_path,
            data=data.encode('utf-8'),
            ordering_key=ordering_key,
            frame_id=str(frame_id),   # Convert frame_id to string
            frame_rate=str(frame_rate)  # Convert frame_rate to string
        )
        frame_id += 1

        start_time = time.time()
        while time.time() - start_time < frame_delay:
            time.sleep(0.001)  # Sleep for a very short time to yield control to other processes

    cap.release()
    logging.debug(f"Completed publishing frames from video stream")

@app.route('/trigger', methods=['POST'])
def trigger():
    request_data = request.get_json()
    bucket_name = request_data['bucket_name']
    video_path = request_data['video_path']
    project_id = request_data['project_id']
    topic_name = request_data['topic_name']

    try:
        # Create a unique task name based on the video details and current timestamp
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
        unique_task_name = hashlib.sha256(f"{bucket_name}/{video_path}/{timestamp}".encode()).hexdigest()
        
        # Create a task for processing the video
        client = tasks_v2.CloudTasksClient()
        project = project_id
        queue = QUEUE_NAME  # Ensure this queue name matches the one you created
        location = LOCATION  # Ensure this matches the location of your queue
        url = f'https://{request.host}/process_video'
        payload = {
            'bucket_name': bucket_name,
            'video_path': video_path,
            'project_id': project_id,
            'topic_name': topic_name
        }
        task = {
            'name': client.task_path(project, location, queue, unique_task_name),
            'http_request': {
                'http_method': tasks_v2.HttpMethod.POST,
                'url': url,
                'headers': {
                    'Content-Type': 'application/json'
                },
                'body': json.dumps(payload).encode()
            }
        }
        parent = client.queue_path(project, location, queue)

        response = client.create_task(parent=parent, task=task)
        logging.debug(f"Created task {response.name}")
        return jsonify({"status": "Task created", "task_name": response.name}), 200
    except Exception as e:
        if "ALREADY_EXISTS" in str(e):
            logging.info(f"Task with name {unique_task_name} already exists.")
            return jsonify({"status": "Task already exists", "task_name": unique_task_name}), 200
        logging.error(f"Failed to create task: {e}")
        return jsonify({"status": "Failed to create task", "error": str(e)}), 500

@app.route('/process_video', methods=['POST'])
def process_video():
    logging.debug("Received process_video request")
    request_data = request.get_json()
    bucket_name = request_data['bucket_name']
    video_path = request_data['video_path']
    project_id = request_data['project_id']
    topic_name = request_data['topic_name']

    # Get video stream from GCS
    video_stream = get_video_stream_from_gcs(bucket_name, video_path)

    # Publish frames to Pub/Sub
    publish_frames_to_pubsub(video_stream, project_id, topic_name)

    return jsonify({"status": "Processing completed"}), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
