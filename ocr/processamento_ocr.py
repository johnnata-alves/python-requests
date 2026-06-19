import os
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import requests

import time
import base64
import uuid

load_dotenv()

DIRECT_LINE_SECRET = os.getenv("COPILOT_API_KEY")
DIRECT_LINE_URL = "https://directline.botframework.com/v3/directline"

IMAGE_PATH = "certidao_obito.jpg"

headers = {
    "Authorization": f"Bearer {DIRECT_LINE_SECRET}"
}

response = requests.post(f"{DIRECT_LINE_URL}/conversations", headers=headers, verify=False)
response.raise_for_status()

conversation = response.json()
conversation_id = conversation["conversationId"]
token = conversation["token"]

print(f"[INFO] Conversation ID: {conversation_id}")

with open(IMAGE_PATH, "rb") as f:
    image_bytes = f.read()

image_base64 = base64.b64encode(image_bytes).decode("utf-8")

activity_url = f"{DIRECT_LINE_URL}/conversations/{conversation_id}/activities"

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

activity = {
    "type": "message",
    "from": {"id": "user1"},
    "text": "Analise este documento e extraia os metadados (certidão de óbito)",
    "attachments": [
        {
            "contentType": "image/jpeg",
            "contentUrl": f"data:image/jpeg;base64,{image_base64}",
            "name": "certidao.jpg"
        }
    ]
}

response = requests.post(activity_url, headers=headers, json=activity, verify=False)
response.raise_for_status()

print("[INFO] Imagem enviada")

watermark = None

while True:
    url = f"{DIRECT_LINE_URL}/conversations/{conversation_id}/activities"
    if watermark:
        url += f"?watermark={watermark}"

    resp = requests.get(url, headers=headers, verify=False)
    resp.raise_for_status()

    data = resp.json()
    watermark = data.get("watermark")

    for activity in data["activities"]:
        if activity["from"]["id"] != "user1":
            print("\n[RESPOSTA DO BOT]")
            print(activity.get("text"))

    time.sleep(2)
