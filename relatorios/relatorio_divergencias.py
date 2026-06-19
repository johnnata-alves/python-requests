import os
from dotenv import load_dotenv
import pymongo
import pandas as pd
from bson import ObjectId
import re
from datetime import datetime, timedelta

load_dotenv()

clientEmissao = pymongo.MongoClient(os.getenv("PRD_MONGO_EMISSAO"))
clientIssuance = pymongo.MongoClient(os.getenv("PRD_MONGO_INSURANCE_PLATFORM"))

dbEmissao = clientEmissao["Pippin"]
dbIssuance = clientIssuance["OrchestratorIssuance"]

issuance_collection = dbEmissao["Issuance"]
flows_collection = dbIssuance["flows"]

issuances = list(issuance_collection.find({"status": "VALIDATED", "created_at": { "$gte":  datetime.now() - timedelta(days=5) }}))

erros = []
correlation_ids_com_erro = []

for issuance in issuances:
    correlation_id = issuance["source"]["external_id"]
    product = issuance["policy"]["product_code"]
    plan = issuance["policy"]["plan_code"]
    ticket = issuance["policy"]["ticket"]

    flow = flows_collection.find_one({"_id": ObjectId(correlation_id)})

    if flow:
        tipo_veiculo = None
        cpf_issuance = issuance.get("insured", {}).get("document")
        cpf_flow = flow.get("payloads", {}).get("quotation_validation", {}).get("request", {}).get("insured", [{}])[0].get("document", {}).get("number")

        molicar_issuance = None
        model_year = None

        if "items" in issuance and isinstance(issuance["items"], list) and issuance["items"]:
            first_item = issuance["items"][0]

            if "items" in first_item:
                molicar_issuance = first_item["items"].get("molicar_code")
                model_year = first_item["items"].get("model_release_year")

        molicar_flow = flow.get("payloads", {}).get("quotation_validation", {}).get("request", {}).get("items", [{}])[0].get("codes", [{}])[0].get("number")
        model_year_flow = flow.get("payloads", {}).get("quotation_validation", {}).get("request", {}).get("items", [{}])[0].get("model", {}).get("year")

        tipo_veiculo_aceite = flow.get("payloads", {}).get("quotation_validation", {}).get("request", {}).get("items", [{}])[0].get("vehicleType", {})
        tipo_veiculo_cotacao = flow.get("payloads", {}).get("quotation", {}).get("request", {}).get("items", [{}])[0].get("vehicleType", {})

        if cpf_issuance and cpf_flow and cpf_issuance != cpf_flow:
            erros.append({"FlowId": correlation_id, "Produto": product, "Plano": plan,"Contrato": ticket,  "Erro": "CPF divergente"})
            correlation_ids_com_erro.append(correlation_id)
            continue

        if molicar_issuance and molicar_flow and re.sub(r"[-]", "", molicar_issuance) != re.sub(r"[-]", "", molicar_flow):
            erros.append({"FlowId": correlation_id, "Produto": product, "Plano": plan,"Contrato": ticket,  "Erro": "Molicar divergente"})
            correlation_ids_com_erro.append(correlation_id)
            continue

        if model_year_flow and model_year and model_year_flow != model_year:
            erros.append({"FlowId": correlation_id, "Produto": product, "Plano": plan,"Contrato": ticket,  "Erro": "Ano modelo divergente"})
            correlation_ids_com_erro.append(correlation_id)
            continue

        if tipo_veiculo_aceite and tipo_veiculo_cotacao and tipo_veiculo_aceite != tipo_veiculo_cotacao:
            erros.append({"FlowId": correlation_id, "Produto": product, "Plano": plan,"Contrato": ticket,  "Erro": "Tipo veículo divergente"})
            correlation_ids_com_erro.append(correlation_id)
            continue

    else:
        erros.append({"FlowId": correlation_id, "Produto": product, "Plano": plan,"Contrato": ticket, "Erro": "Registro não encontrado em flows"})

df_erros = pd.DataFrame(erros)
agora = datetime.now().strftime("%Y%m%d_%H%M%S")

nome_arquivo = f"erros_validacao_{agora}.xlsx"

print("Arquivo 'erros_validacao.xlsx' gerado com os registros divergentes.")

if correlation_ids_com_erro:
    issuance_collection.update_many(
        {"source.external_id": {"$in": correlation_ids_com_erro}},
        {"$set": {"status": "VALIDATION_ERROR"}}
    )
