import os
import time
import warnings
import urllib3
import requests
from dotenv import load_dotenv

load_dotenv()

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

COPILOT_API_KEY = os.getenv("COPILOT_API_KEY")
BASE_URL = os.getenv("DIRECT_LINE_BASE_URL", "https://directline.botframework.com/v3/directline")
USER_ID = "copilot-chat-user"
MODEL          = "gpt-5.1"
PERGUNTA       = "Me fale tudo sobre a Too Seguros"

POLL_ATTEMPTS  = 30
POLL_INTERVAL  = 2

HEADERS = {
    "Authorization": f"Bearer {COPILOT_API_KEY}",
    "Content-Type": "application/json",
}

def criar_conversa() -> str:
    r = requests.post(f"{BASE_URL}/conversations", headers=HEADERS, timeout=30, verify=False)
    r.raise_for_status()
    conversation_id = r.json()["conversationId"]
    print(f"Conversa criada: {conversation_id}")
    return conversation_id

def enviar_mensagem(conversation_id: str, texto: str):
    mensagem_completa = f"{texto}"
    payload = {
        "type": "message",
        "from": {"id": USER_ID},
        "text": mensagem_completa,
        "channelData": {"model": MODEL},
    }
    r = requests.post(
        f"{BASE_URL}/conversations/{conversation_id}/activities",
        headers=HEADERS,
        json=payload,
        timeout=30,
        verify=False,
    )
    r.raise_for_status()
    print(f"Mensagem enviada.")

def aguardar_resposta(conversation_id: str) -> str:
    watermark = None
    for tentativa in range(1, POLL_ATTEMPTS + 1):
        params = {"watermark": watermark} if watermark else {}
        r = requests.get(
            f"{BASE_URL}/conversations/{conversation_id}/activities",
            headers=HEADERS,
            params=params,
            timeout=30,
            verify=False,
        )
        r.raise_for_status()
        payload = r.json()
        watermark = payload.get("watermark")

        respostas = [
            a["text"]
            for a in payload.get("activities", [])
            if a.get("type") == "message"
            and a.get("text")
            and a.get("from", {}).get("id", "").lower() != USER_ID.lower()
        ]

        if respostas:
            print(f"Resposta recebida na tentativa {tentativa}.")
            return respostas[-1]

        print(f"  Aguardando... ({tentativa}/{POLL_ATTEMPTS})")
        time.sleep(POLL_INTERVAL)

    raise TimeoutError("Sem resposta dentro do tempo limite.")

def main():
    conversation_id = criar_conversa()
    enviar_mensagem(conversation_id, PERGUNTA)
    resposta = aguardar_resposta(conversation_id)

    print("\n--- PERGUNTA ---")
    print(PERGUNTA)
    print("\n--- RESPOSTA ---")
    print(resposta)

if __name__ == "__main__":
    main()
