import os
from dotenv import load_dotenv
from pymongo import MongoClient
import pika
import json
from datetime import datetime, timezone

load_dotenv()

MONGO_URI = os.getenv("HML_MONGO_URI")
DB_NAME_1 = "ClaimEngine"
COLLECTION_1 = "Attachment"

DB_NAME_2 = "DocumentTypification"
COLLECTION_2 = "TypificationDocument"

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5671"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST")
RABBITMQ_QUEUE = "service.document.document-typification.intake"

FILTER_DATE = datetime(2026, 4, 10, 0, 0, 0, tzinfo=timezone.utc)

mongo_client = MongoClient(MONGO_URI)

db1 = mongo_client[DB_NAME_1]
attachment_col = db1[COLLECTION_1]

db2 = mongo_client[DB_NAME_2]
typification_col = db2[COLLECTION_2]

import ssl

credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
context = ssl.create_default_context()
ssl_options = pika.SSLOptions(context, RABBITMQ_HOST)
parameters = pika.ConnectionParameters(
    host=RABBITMQ_HOST,
    port=RABBITMQ_PORT,
    virtual_host=RABBITMQ_VHOST,
    credentials=credentials,
    ssl_options=ssl_options
)
rabbit_connection = pika.BlockingConnection(parameters)
channel = rabbit_connection.channel()

from datetime import timedelta

now_utc = datetime.now(timezone.utc)
limit_12h = now_utc - timedelta(hours=48)

query = {
    "UpdatedAt": {
        "$gte": FILTER_DATE,
        "$lte": limit_12h
    },
    "metadataValidationSuccess": False
}

cursor_limit = 10
total_docs = min(attachment_col.count_documents(query), cursor_limit)
print(f"Total de documentos a processar: {total_docs}")

cursor = attachment_col.aggregate([
    {"$match": query},
    {"$sample": {"size": cursor_limit}}
])
processed = 0

for doc in cursor:
    try:
        doc_id = doc["_id"]

        request = doc.get("documentTypificationCall", {}).get("request")

        correlation_id = doc.get("documentTypificationCall", {}).get("correlationId")

        if not request:
            print(f"[SKIP] Sem request: {doc_id}")
            processed += 1
            percent = (processed / total_docs) * 100 if total_docs else 0
            print(f"Andamento: {processed}/{total_docs} ({percent:.2f}%)")
            continue

        request_payload = None
        try:
            request_payload = json.loads(request) if isinstance(request, str) else dict(request)
        except Exception:
            request_payload = None

        if isinstance(request_payload, dict):
            request_payload["TenantId"] = "4"
            request = json.dumps(request_payload, ensure_ascii=False)
        else:
            print(f"[SKIP] Request inválido para ajuste de TenantId: {doc_id}")
            processed += 1
            percent = (processed / total_docs) * 100 if total_docs else 0
            print(f"Andamento: {processed}/{total_docs} ({percent:.2f}%)")
            continue

        if correlation_id:
            print(f"Buscando file_hash para correlation_id: {correlation_id}")
            doc_typification = typification_col.find_one({"correlation_id": correlation_id})
            if doc_typification and "file_hash" in doc_typification:
                file_hash = doc_typification["file_hash"]
                print(f"Deletando todos com file_hash: {file_hash}")
                result = typification_col.delete_many({"file_hash": file_hash})
                print(f"Removidos {result.deleted_count} documentos com file_hash {file_hash}")
            else:
                print(f"Deletando por correlation_id: {correlation_id}")
                result = typification_col.delete_many({"correlation_id": correlation_id})
                print(f"Removidos {result.deleted_count} documentos com correlation_id {correlation_id}")

        channel.basic_publish(
            exchange="",
            routing_key=RABBITMQ_QUEUE,
            body=request.encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2
            )
        )
        print(f"Publicado no RabbitMQ: {doc_id}")

        attachment_col.update_one(
            {"_id": doc_id},
            {"$set": {"status": "Pending"}}
        )
        print(f"Status atualizado para Pending: {doc_id}")

        print(f"[OK] Processado: {doc_id}")

    except Exception as e:
        print(f"[ERRO] {doc.get('_id')} -> {e}")
    finally:
        processed += 1
        percent = (processed / total_docs) * 100 if total_docs else 0
        print(f"Andamento: {processed}/{total_docs} ({percent:.2f}%)")

rabbit_connection.close()
mongo_client.close()
