import os
import time
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DB_NAME = "SinistrosMicroService"
COLLECTION = "SinistroTimeline_exported"

INTERVAL = int(os.getenv("CLEANUP_INTERVAL", "60"))  # segundos

FILTER = {
    "$or": [
        {"ParceiroNotificado": False},
        {
            "InformacaoAdicional.Detalhes": {
                "$not": {"$elemMatch": {"Chave": "Parceiro", "Valor": "PAN"}}
            }
        },
    ]
}


def main():
    client = MongoClient(MONGO_URI)
    col = client[DB_NAME][COLLECTION]
    print(f"Limpeza a cada {INTERVAL}s em {DB_NAME}.{COLLECTION}. Ctrl+C para parar.")

    while True:
        try:
            result = col.delete_many(FILTER)
            print(f"[{datetime.now():%H:%M:%S}] Removidos: {result.deleted_count}")
        except Exception as exc:
            print(f"[{datetime.now():%H:%M:%S}] Erro: {exc}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
