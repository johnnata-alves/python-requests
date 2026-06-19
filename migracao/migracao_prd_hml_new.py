import os
import sys
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("migrate")

PRD_MONGO_URI = os.getenv("PRD_MONGO_URI")
HML_MONGO_URI = os.getenv("HML_MONGO_URI")
PRD_S3_BUCKET = os.getenv("PRD_S3_BUCKET")
HML_S3_BUCKET = os.getenv("HML_S3_BUCKET")
MIGRATION_TAG = "carga prod"
PER_STATUS_LIMIT = 10

REQUESTOR = {
    "acceptsCommunication": True,
    "communicationType": "Email",
    "requestorIsInsured": False,
    "name": "Johnnata Alves",
    "socialName": None,
    "documentType": "CPF",
    "documentNumber": "39096789806",
    "relationship": "FATHER",
    "phones": [{"countryCallingCode": "55", "areaCode": "11", "number": "977493547", "principal": False}],
    "emails": [{"email": "johnnata.alves@tooseguros.com.br", "principal": True}],
}

RELATED_BY_PROTOCOL = ["Attachment", "Beneficiary", "Letter", "PendingIssue", "Person", "Timeline"]
RELATED_BY_FLOWID = ["Document", "TechnicalOpinion", "ClaimScore"]

client_prd = MongoClient(PRD_MONGO_URI)
client_hml = MongoClient(HML_MONGO_URI)
db_prd = client_prd["ClaimEngine"]
db_hml = client_hml["ClaimEngine"]

s3_prd = boto3.client("s3",
    aws_access_key_id=os.getenv("PRD_AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("PRD_AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("PRD_AWS_REGION", "us-east-1"))

s3_hml = boto3.client("s3",
    aws_access_key_id=os.getenv("HML_AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("HML_AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("HML_AWS_REGION", "us-east-1"))

def prefixar(valor):
    if valor is None:
        return None
    s = str(valor)
    return s if s.startswith("9") else f"9{s}"

def prefixar_doc(doc):
    novo = dict(doc)
    novo.pop("_id", None)
    for campo in ["protocol", "flowId", "FlowId"]:
        if campo in novo and novo[campo] is not None:
            novo[campo] = prefixar(novo[campo])
    return novo

def ja_migrado(protocol):
    return db_hml["Notification"].count_documents({"protocol": prefixar(protocol)}, limit=1) > 0

def copiar_s3(key):
    if not key:
        return
    try:
        s3_hml.head_object(Bucket=HML_S3_BUCKET, Key=key)
        return
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
            raise
    try:
        obj = s3_prd.get_object(Bucket=PRD_S3_BUCKET, Key=key)
        s3_hml.put_object(Bucket=HML_S3_BUCKET, Key=key, Body=obj["Body"].read())
        log.info("S3 copiado: %s", key)
    except Exception as e:
        log.error("S3 erro: %s - %s", key, e)

def migrar_notification(doc):
    novo = prefixar_doc(doc)
    novo["requestor"] = REQUESTOR
    if "additionalInformation" not in novo or not isinstance(novo.get("additionalInformation"), dict):
        novo["additionalInformation"] = {}
    novo["additionalInformation"]["migration"] = MIGRATION_TAG
    novo["CreatedAt"] = datetime.now(timezone.utc)
    db_hml["Notification"].insert_one(novo)

def migrar_attachments(protocol):
    prefixed_protocol = prefixar(protocol)
    db_hml["Attachment"].delete_many({"protocol": prefixed_protocol})

    prd_docs = list(db_prd["Attachment"].find({"protocol": protocol}))
    if not prd_docs:
        return {}

    id_map = {}
    for doc in prd_docs:
        old_id = doc["_id"]
        novo = prefixar_doc(doc)
        result = db_hml["Attachment"].insert_one(novo)
        id_map[old_id] = result.inserted_id
        copiar_s3(doc.get("key"))

    log.info("  Attachment: %d doc(s) migrados", len(prd_docs))
    return id_map

def migrar_documents(flow_id, attachment_id_map):
    prefixed_flow = prefixar(flow_id)
    db_hml["Document"].delete_many({"flowId": prefixed_flow})

    prd_docs = list(db_prd["Document"].find({"flowId": flow_id}))
    if not prd_docs:
        return

    for doc in prd_docs:
        novo = prefixar_doc(doc)

        old_attachments = novo.get("attachments", [])
        if old_attachments:
            novo["attachments"] = [
                attachment_id_map.get(old_id, old_id) for old_id in old_attachments
            ]

        db_hml["Document"].insert_one(novo)

    log.info("  Document: %d doc(s) migrados (attachments remapeados)", len(prd_docs))

def migrar_collection(coll_name, filter_field, valor_original):
    prefixed_value = prefixar(valor_original)
    db_hml[coll_name].delete_many({filter_field: prefixed_value})

    prd_docs = list(db_prd[coll_name].find({filter_field: valor_original}))
    if not prd_docs:
        alt_field = "FlowId" if filter_field == "flowId" else "flowId" if filter_field == "FlowId" else None
        if alt_field:
            db_hml[coll_name].delete_many({alt_field: prefixed_value})
            prd_docs = list(db_prd[coll_name].find({alt_field: valor_original}))
            if prd_docs:
                filter_field = alt_field
    if not prd_docs:
        return

    for doc in prd_docs:
        novo = prefixar_doc(doc)

        if coll_name == "ClaimScore":
            novo["status"] = "Pending"
            novo["newTimeline"] = False

        db_hml[coll_name].insert_one(novo)

    log.info("  %s: %d doc(s) migrados", coll_name, len(prd_docs))

def migrar_relacionadas(protocol, flow_id):
    attachment_id_map = migrar_attachments(protocol)

    for coll in RELATED_BY_PROTOCOL:
        if coll == "Attachment":
            continue
        migrar_collection(coll, "protocol", protocol)

    if flow_id:
        migrar_documents(flow_id, attachment_id_map)

        for coll in RELATED_BY_FLOWID:
            if coll == "Document":
                continue
            filter_field = "FlowId" if coll == "TechnicalOpinion" else "flowId"
            migrar_collection(coll, filter_field, flow_id)

WORKERS = int(os.getenv("WORKERS", "1"))
lock = threading.Lock()
contadores = {"migradas": 0, "puladas": 0, "erros": 0}

def processar_notification(doc):
    protocol = doc.get("protocol")
    flow_id = doc.get("flowId")

    if not protocol:
        return

    if ja_migrado(protocol):
        log.info("  [SKIP] protocol=%s já migrado", protocol)
        with lock:
            contadores["puladas"] += 1
        return

    try:
        migrar_notification(doc)
        migrar_relacionadas(protocol, flow_id)
        with lock:
            contadores["migradas"] += 1
        log.info("  [OK] protocol=%s migrado", protocol)
    except Exception as e:
        with lock:
            contadores["erros"] += 1
        log.error("  [ERRO] protocol=%s: %s", protocol, e)

def main():
    statuses = db_prd["Notification"].distinct("status")
    log.info("Status encontrados em PRD: %s", statuses)

    all_docs = []
    for status in statuses:
        docs = list(db_prd["Notification"].find({"status": {"$regex": "Aguardando Vistoria", "$options": "i"}}).limit(PER_STATUS_LIMIT))
        log.info("Status '%s': %d notification(s)", status, len(docs))
        all_docs.extend(docs)

    log.info("Total a processar: %d notifications", len(all_docs))

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(processar_notification, doc): doc for doc in all_docs}
        for future in as_completed(futures):
            future.result()

    log.info("Finalizado. Migradas: %d | Puladas: %d | Erros: %d",
             contadores["migradas"], contadores["puladas"], contadores["erros"])
    client_prd.close()
    client_hml.close()

if __name__ == "__main__":
    main()
