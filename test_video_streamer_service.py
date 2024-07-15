import requests
import json
import logging
import cv2
import numpy as np
import base64
from google.cloud import pubsub_v1
from concurrent.futures import TimeoutError
from collections import deque
import threading
import time

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Set up Pub/Sub subscription parameters
PROJECT_ID = 'your-project-id'
TOPIC_NAME = 'your-topic'
SUBSCRIPTION_NAME = 'your-subscription'
TIMEOUT = 60.0  # Timeout for Pub/Sub subscription
BUFFER_SIZE = 60  # Buffer size for frames

frame_buffer = {}
frame_rate = 30.0  # Default frame rate
expected_frame_id = 0  # Track the next expected frame ID
lock = threading.Lock()

def trigger_service(url, bucket_name, video_path, project_id, topic_name):
    headers = {
        'Content-Type': 'application/json',
    }

    payload = {
        'bucket_name': bucket_name,
        'video_path': video_path,
        'project_id': project_id,
        'topic_name': topic_name,
    }

    logging.debug(f"Sending POST request to {url} with payload: {payload}")

    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        
        logging.debug(f"Received response with status code: {response.status_code}")

        if response.status_code == 200:
            logging.info('Service triggered successfully.')
            logging.debug(f"Response: {response.json()}")
        else:
            logging.error('Failed to trigger service.')
            logging.debug(f"Status Code: {response.status_code}")
            logging.debug(f"Response: {response.text}")
    except Exception as e:
        logging.error(f"Exception occurred while making POST request: {e}")

def subscribe_to_pubsub(project_id, subscription_name, timeout=60.0):
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(project_id, subscription_name)

    def callback(message):
        global frame_rate, expected_frame_id
        logging.info(f"Received message with attributes: {message.attributes}")
        try:
            frame_id = int(message.attributes.get('frame_id', -1))
            if frame_id < expected_frame_id:
                logging.debug(f"Skipping old frame: {frame_id}")
                message.ack()
                return

            frame_bytes = base64.b64decode(message.data)
            np_arr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            frame_rate = float(message.attributes.get('frame_rate', 30.0))

            with lock:
                frame_buffer[frame_id] = frame
                if len(frame_buffer) > BUFFER_SIZE:
                    min_frame_id = min(frame_buffer.keys())
                    del frame_buffer[min_frame_id]

            message.ack()
        except Exception as e:
            logging.error(f"Error processing message: {e}")
            message.nack()

    streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
    logging.info(f"Listening for messages on {subscription_path}...")

    try:
        streaming_pull_future.result(timeout=timeout)
    except TimeoutError:
        streaming_pull_future.cancel()
        streaming_pull_future.result()
    finally:
        cv2.destroyAllWindows()

def display_frames():
    global frame_rate, expected_frame_id
    while True:
        with lock:
            if expected_frame_id in frame_buffer:
                frame = frame_buffer.pop(expected_frame_id)
                expected_frame_id += 1
            else:
                frame = None

        if frame is not None:
            cv2.imshow('Video Stream', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        else:
            time.sleep(1.0 / frame_rate)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    CLOUD_RUN_URL = 'https://pubsub-video-streamer-ec3q4rsmra-uc.a.run.app'
    BUCKET_NAME = 'cloud-racer'
    VIDEO_PATH = 'data/raw_data/yolov8n-car_front-rear-2023_London_Highlights.mp4'
    PROJECT_ID = 'racer-428819'
    TOPIC_NAME = 'video-stream'
    SUBSCRIPTION_NAME = 'video-stream-test-sub'

    logging.info("Starting test script...")

    # Start the frame display thread
    display_thread = threading.Thread(target=display_frames)
    display_thread.start()

    # Subscribe to the Pub/Sub topic and buffer messages
    subscribe_to_pubsub(PROJECT_ID, SUBSCRIPTION_NAME, TIMEOUT)

    # Trigger the Cloud Run service
    trigger_service(CLOUD_RUN_URL, BUCKET_NAME, VIDEO_PATH, PROJECT_ID, TOPIC_NAME)

    logging.info("Test script completed.")
 