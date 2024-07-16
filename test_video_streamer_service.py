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
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')

# Read configuration from config.json
with open('config.json') as config_file:
    config = json.load(config_file)

CLOUD_RUN_URL = config['CLOUD_RUN_URL']
BUCKET_NAME = config['BUCKET_NAME']
VIDEO_PATH = config['VIDEO_PATH']
PROJECT_ID = config['PROJECT_ID']
TOPIC_NAME = config['TOPIC_NAME']
SUBSCRIPTION_NAME = config['SUBSCRIPTION_NAME']
TIMEOUT = 60.0  # Timeout for Pub/Sub subscription
BUFFER_SIZE = 60  # Buffer size for frames

frame_buffer = deque(maxlen=BUFFER_SIZE)
frame_rate = 30.0  # Default frame rate

def trigger_service(url, bucket_name, video_path, project_id, topic_name):
    
    url += '/trigger'
    
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
        global frame_rate
        logging.info(f"Received message with attributes: {message.attributes}")
        try:
            frame_bytes = base64.b64decode(message.data)
            np_arr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            frame_rate = float(message.attributes.get('frame_rate', 30.0))

            frame_buffer.append(frame)

            #message.ack()
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
    global frame_rate
    cv2.namedWindow('Video Stream', cv2.WINDOW_NORMAL)
    while True:
        if frame_buffer:
            frame = frame_buffer.popleft()
            cv2.imshow('Video Stream', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        else:
            time.sleep(1.0 / frame_rate)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    logging.info("Starting test script...")

    # Trigger the Cloud Run service
    trigger_service(CLOUD_RUN_URL, BUCKET_NAME, VIDEO_PATH, PROJECT_ID, TOPIC_NAME)

    # Start the frame display thread
    display_thread = threading.Thread(target=display_frames)
    display_thread.start()

    # Subscribe to the Pub/Sub topic and buffer messages
    subscribe_to_pubsub(PROJECT_ID, SUBSCRIPTION_NAME, TIMEOUT)

    logging.info("Test script completed.")
