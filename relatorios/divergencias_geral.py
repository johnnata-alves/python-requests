import os

import pymongo
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

def create_mongo_connection(uri):
    """Cria uma conexão MongoDB segura."""
    try:
        return pymongo.MongoClient(uri)
    except pymongo.errors.ConnectionFailure as e:
        print(f"Erro ao conectar ao MongoDB: {e}")
        return None

clientEmissao = create_mongo_connection(os.getenv("PRD_MONGO_EMISSAO"))

clientIssuance = create_mongo_connection(os.getenv("PRD_MONGO_INSURANCE_PLATFORM"))

if not clientEmissao or not clientIssuance:
    exit("Falha ao conectar ao MongoDB. Encerrando script.")

dbEmissao = clientEmissao["Pippin"]
dbIssuance = clientIssuance["OrchestratorIssuance"]

issuance_collection = dbEmissao["Issuance"]
flows_collection = dbIssuance["flows"]

data_minima = int((datetime.utcnow() - timedelta(days=5)).timestamp())

def get_pipeline(type_check):
    """Gera pipeline baseado no tipo de verificação ('CPF' ou 'Código')."""
    match_condition = {
        "payloads.quotation_validation.request": {"$exists": True},
        "payloads.quotation_validation.request.items.loanProtectionCode": {"$not": {"$regex": "CP-", "$options": "i"}},
        "history.0.created_at": {"$gte": data_minima}
    }

    project_fields = {
        "_id": 1,
        "quotation_document": {"$arrayElemAt": ["$payloads.quotation.request.insured.document.number", 0]},
        "validation_document": {"$arrayElemAt": ["$payloads.quotation_validation.request.insured.document.number", 0]},
        "loanProtectionCode": {"$arrayElemAt": ["$payloads.quotation_validation.request.items.loanProtectionCode", 0]},
        "quotation_code": {"$arrayElemAt": ["$payloads.quotation.request.items.codes.number", 0]},
        "validation_code": {"$arrayElemAt": ["$payloads.quotation_validation.request.items.codes.number", 0]},
        "quotation_year": {"$arrayElemAt": ["$payloads.quotation.request.items.model.year", 0]},
        "validation_year": {"$arrayElemAt": ["$payloads.quotation_validation.request.items.model.year", 0]}
    }

    match_expr = {"$ne": ["$quotation_document", "$validation_document"]} if type_check == "CPF" else {
        "$and": [
            {"$eq": ["$quotation_document", "$validation_document"]},
            {"$ne": ["$quotation_code", "$validation_code"]}
        ]
    }

    return [
        {"$match": match_condition},
        {"$project": project_fields},
        {"$match": {"$expr": match_expr}},
        {"$addFields": {"status": "CPF diferente" if type_check == "CPF" else "CPF igual porém Código diferente"}}
    ]

cpf_diferente = list(flows_collection.aggregate(get_pipeline("CPF")))
codigo_diferente = list(flows_collection.aggregate(get_pipeline("Código")))

diferentes = cpf_diferente + codigo_diferente

def buscar_dados_politica(external_id):
    """Busca informações de política no banco de emissão."""
    return issuance_collection.find_one(
        {"source.external_id": str(external_id)},
        {"policy.policy_code": 1, "policy.product_code": 1, "policy.plan_code": 1, "status": 1}
    )

resultado = []
for doc in diferentes:
    policy_data = buscar_dados_politica(doc["_id"])

    resultado.append({
        "_id": doc["_id"],
        "quotation_document": doc.get("quotation_document"),
        "validation_document": doc.get("validation_document"),
        "loanProtectionCode": doc.get("loanProtectionCode"),
        "quotation_code": doc.get("quotation_code")[0] if isinstance(doc.get("quotation_code"), list) and doc.get("quotation_code") else doc.get("quotation_code"),
        "validation_code": doc.get("validation_code")[0] if isinstance(doc.get("validation_code"), list) and doc.get("validation_code") else doc.get("validation_code"),
        "quotation_year": doc.get("quotation_year"),
        "validation_year": doc.get("validation_year"),
        "policy_code": policy_data.get("policy", {}).get("policy_code") if policy_data else None,
        "product": policy_data.get("policy", {}).get("product_code") if policy_data else None,
        "plan": policy_data.get("policy", {}).get("plan_code") if policy_data else None,
        "status": policy_data.get("status") if policy_data else None,
        "validation_status": doc.get("status")
    })

df = pd.DataFrame(resultado)
df.to_excel("resultado_validacao6.xlsx", index=False)

print(f"Arquivo 'resultado_validacao.xlsx' gerado com sucesso. Total de registros: {len(resultado)}")
