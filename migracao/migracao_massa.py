import base64
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import boto3
import requests
import urllib3
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MONGO_PRD = os.getenv("PRD_MONGO_CLAIM_ENGINE")
MONGO_HML = os.getenv("HML_MONGO_URI")
MONGO_INDEXED = os.getenv("HML_INDEXED_MONGO_URI")

LIMIT = 1000000
MAX_WORKERS = 8

API_NOTIFICATION = "https://claim-engine-api.stg.tooseguros.com.br/api/v1/Notification"
API_ATTACHMENT = "https://claim-engine-api.stg.tooseguros.com.br/api/v1/Attachment/external"

TOKEN_URL = os.getenv("KEYCLOAK_TOKEN_URL")
TOKEN_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID")
TOKEN_USERNAME = os.getenv("KEYCLOAK_USERNAME")
TOKEN_PASSWORD = os.getenv("KEYCLOAK_PASSWORD")

S3_BUCKET = os.getenv("PRD_S3_BUCKET")
S3_REGION = os.getenv("PRD_AWS_REGION")
AWS_ACCESS_KEY_ID = os.getenv("PRD_AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("PRD_AWS_SECRET_ACCESS_KEY")

s3 = boto3.client(
    "s3",
    region_name=S3_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

def format_filename(key: str) -> str:
    name = key.split("/")[-1]
    name = name.split("_", 1)[-1]
    name = re.sub(r"_[^_]+\.", ".", name)
    return name

def download_s3_base64(key):
    obj = s3.get_object(Bucket=S3_BUCKET, Key=key)
    return base64.b64encode(obj["Body"].read()).decode("utf-8")

def get_token():
    response = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "password",
            "client_id": TOKEN_CLIENT_ID,
            "username": TOKEN_USERNAME,
            "password": TOKEN_PASSWORD,
        },
        verify=False
    )
    response.raise_for_status()
    return response.json()["access_token"]

def create_notification(payload, token):
    response = requests.post(
        API_NOTIFICATION,
        json=payload,
        headers={"x-auth-appname": "claim-engine-api", "Authorization": f"Bearer {token}"},
        verify=False
    )
    response.raise_for_status()
    response_data = response.json()
    if isinstance(response_data, list):
        if not response_data:
            raise ValueError("Resposta da Notification veio vazia")
        return response_data[0]
    return response_data

def send_attachment(payload, token):
    response = requests.post(
        API_ATTACHMENT,
        json=payload,
        headers={"x-auth-appname": "claim-engine-api", "Authorization": f"Bearer {token}"},
        verify=False
    )
    response.raise_for_status()

def resolve_cause_type(hml, coverage, cause_type_code):
    if cause_type_code is None:
        return None
    cov_doc = hml["Coverage"].find_one({
        "coverage": coverage,
        "causeTypes.causeTypeCode": int(cause_type_code)
    })
    if not cov_doc:
        return None
    return next(
        (ct["causeType"] for ct in cov_doc.get("causeTypes", [])
         if ct.get("causeTypeCode") == int(cause_type_code)),
        None
    )

def resolve_document_type(hml, suggested_code):
    if suggested_code is None:
        return None

    if isinstance(suggested_code, str):
        suggested_code = suggested_code.strip()
        if not suggested_code:
            return None

    try:
        erp_document_id = int(suggested_code)
    except (TypeError, ValueError):
        return None

    doc_mapping = hml["DocumentTypeMappings"].find_one({"ERPDocumentId": erp_document_id})
    return doc_mapping.get("document") if doc_mapping else None

def build_notification_payload(doc, doc_number, coverage, hml):
    return {
        "occurrenceDate": doc["occurrenceDate"].isoformat(),
        "certificate": doc["certificate"],
        "notificationDate": doc["notificationDate"].isoformat(),
        "occurrenceDescription": "Carga de dados - Migração",
        "requestor": {
            "acceptsCommunication": True,
            "communicationType": "EmailSMS",
            "requestorIsInsured": False,
            "name": "Johnnata Alves",
            "socialName": None,
            "documentType": "CPF",
            "documentNumber": "39096789806",
            "relationship": "PARTNER",
            "phones": [{"countryCallingCode": "+55", "areaCode": "11", "number": "977493547", "principal": True}],
            "emails": [{"email": "johnnata.alves@tooseguros.com.br", "principal": True}]
        },
        "insured": {"documentNumber": doc_number},
        "cause": doc.get("cause"),
        "causeType": resolve_cause_type(hml, coverage, doc.get("causeType")),
        "occurrenceCodeUf": doc.get("occurrenceCodeUf"),
        "occurrenceNameCity": doc.get("occurrenceNameCity"),
        "protocol": doc.get("protocol"),
        "coverage": coverage,
        "notificationOrigin": doc.get("notificationOrigin"),
        "additionalInformation": doc.get("additionalInformation", {}),
        "balanceDue": 0
    }

def build_attachment_payload(att, new_protocol, hml):
    key = att["key"]
    return {
        "attachment": download_s3_base64(key),
        "protocol": new_protocol,
        "fileName": format_filename(key),
        "notes": att.get("notes"),
        "document": resolve_document_type(hml, att.get("suggestedDocumentCode")),
        "beneficiaryCode": 0,
        "origin": att.get("origin")
    }

def already_exists(hml, doc_number, coverage):
    return hml.Notification.find_one({
        "insured.documentNumber": doc_number,
            "coverage": coverage
        })

def validate_policy(hml_indexed_policy_too, doc_number, policy_number):
    return hml_indexed_policy_too.person_branch_catalog.find_one({
        "insured_document": doc_number,
        "policy_number": str(policy_number)
    })

def validate_stakeholder(hml_indexed_stakeholders, doc_number):
    return hml_indexed_stakeholders.identification.find_one({"document": doc_number})

def resolve_endorsement(client_hml, policy_number, indexed_catalog, person_id_erp):
    collection_name = f"{indexed_catalog}_items"
    client_endorsement = MongoClient(MONGO_INDEXED)
    db = client_endorsement["indexed_endorsement"]
    return db[collection_name].find_one({
        "policy_number": str(policy_number),
        "person_id": int(person_id_erp)
    })

def process_attachments(prd, hml, doc, new_protocol, token):
    attachments = prd.Attachment.find({"protocol": doc.get("protocol"), "key": {"$exists": True}})
    for att in attachments:
        try:
            print(f"📎 Enviando anexo: {format_filename(att['key'])}")
            payload_att = build_attachment_payload(att, new_protocol, hml)
            send_attachment(payload_att, token)
            print("✔ Anexo enviado")
        except Exception as e:
            print(f"❌ Erro no anexo: {e}")

def process_notification(doc, prd, hml, hml_indexed_policy_too, hml_indexed_stakeholders, client_hml, token):
    protocol = doc.get("protocol")
    print(f"\n🔎 Processando protocolo: {protocol}")

    doc_number = doc["insured"]["documentNumber"]
    coverage = doc["coverage"]

    if already_exists(hml, doc_number, coverage):
        print("⏭ Já existe no HML. Pulando.")
        return False

    policy = validate_policy(hml_indexed_policy_too, doc_number, doc["policyNumber"])
    if not policy:
        print("❌ Policy não encontrada.")
        return False

    stakeholder = validate_stakeholder(hml_indexed_stakeholders, doc_number)
    if not stakeholder:
        print("❌ Stakeholder não encontrado.")
        return False

    person_id_erp = stakeholder.get("personIdErp")
    indexed_catalog = policy.get("indexed_catalog")

    if not resolve_endorsement(client_hml, doc["policyNumber"], indexed_catalog, person_id_erp):
        print("❌ Endosso não encontrado.")
        return False

    payload = build_notification_payload(doc, doc_number, coverage, hml)

    try:
        response = create_notification(payload, token)
        new_protocol = response.get("protocol")
        print(f"✅ Criado no HML. Novo protocolo: {new_protocol}")
    except Exception as e:
        print(f"❌ Erro ao criar notification: {e}")
        return False

    process_attachments(prd, hml, doc, new_protocol, token)
    time.sleep(0.5)
    return True

def main():
    client_prd = MongoClient(MONGO_PRD)
    client_hml = MongoClient(MONGO_HML)
    client_indexed_policy_too = MongoClient(MONGO_INDEXED)
    client_indexed_stakeholders = MongoClient(MONGO_INDEXED)

    prd = client_prd["ClaimEngine"]
    hml = client_hml["ClaimEngine"]
    hml_indexed_policy_too = client_indexed_policy_too["indexed_policy_too"]
    hml_indexed_stakeholders = client_indexed_stakeholders["indexed_stakeholders"]

    filter_query = {"status": {"$ne": "Recusado"}}
    total_notifications = prd.Notification.count_documents(filter_query)
    total_to_process = min(LIMIT, total_notifications)

    token = get_token()
    print("✅ Token obtido com sucesso")

    if total_to_process == 0:
        print("Nenhuma notificação encontrada para processar.")
        return

    notifications = list(prd.Notification.find(filter_query).limit(total_to_process))
    print(f"🚀 Iniciando processamento com {MAX_WORKERS} threads ({total_to_process} notificações)...")

    completed = 0
    successful = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(
                process_notification,
                doc,
                prd,
                hml,
                hml_indexed_policy_too,
                hml_indexed_stakeholders,
                client_hml,
                token,
            )
            for doc in notifications
        ]

        for future in as_completed(futures):
            completed += 1
            try:
                if future.result():
                    successful += 1
            except Exception as e:
                print(f"❌ Erro inesperado na thread: {e}")

            percentage = (completed / total_to_process) * 100
            print(
                f"📊 Progresso: {completed}/{total_to_process} "
                f"({percentage:.1f}%) | Sucesso: {successful}"
            )

    print(f"\n🏁 Finalizado | Total: {total_to_process} | Sucesso: {successful} | Falhas/Pulos: {total_to_process - successful}")

if __name__ == "__main__":
    main()
