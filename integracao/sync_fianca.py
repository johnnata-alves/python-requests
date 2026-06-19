import os
from dotenv import load_dotenv
import pyodbc
from pymongo import MongoClient
from datetime import datetime, date
import random
import requests
from sql_query import QUERY

load_dotenv()

sql_conn = pyodbc.connect(os.getenv("SQL_CONNECTION_I4PRO_HML"))
mongo = MongoClient(os.getenv("HML_MONGO_URI"))
db = mongo["SinistrosMicroService"]

def protocolo():
    response = requests.post(
        "http://10.30.102.93/v1",
        headers={"clientID": os.getenv("INTERNAL_CLIENT_ID")},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if "protocolNumber" not in data:
        raise RuntimeError("Resposta inválida do serviço de protocolo.")
    return data["protocolNumber"]

def cobertura_integrada(valor):
    r = db.CoberturaConfiguracao.find_one({"CoberturasIntegracao.CoberturaId": int(valor)})
    if not r:
        return None
    return {"_id": int(r["CoberturaId"]), "GrupoCoberturaId": int(r["GrupoCoberturaId"]), "TipoCausaId": int(r["TipoCausaId"]), "SaldoDevedor": None}

def to_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return value

cursor = sql_conn.cursor()
cursor.execute(QUERY)
while cursor.description is None:
    if not cursor.nextset():
        break

if cursor.description is None:
    sql_conn.close()
    mongo.close()
    raise RuntimeError("A consulta SQL não retornou nenhum conjunto de resultados.")

rows_by_contract = {}

for r in cursor.fetchall():
    contract_key = str(r.contract)
    if contract_key not in rows_by_contract:
        rows_by_contract[contract_key] = {
            "row": r,
            "coverages": [],
            "coverage_id_set": set(),
            "accounts": [],
            "account_cpf_set": set()
        }

    if r.coverage_code is not None:
        cov_id = int(r.coverage_code)
        if cov_id not in rows_by_contract[contract_key]["coverage_id_set"]:
            rows_by_contract[contract_key]["coverage_id_set"].add(cov_id)
            rows_by_contract[contract_key]["coverages"].append({
                "IdCobertura": cov_id,
                "Nome": r.coverage,
                "MultaAplicada": False,
                "QuantidadeEmAberto": 1,
                "Valor": str(r.coverage_value),
                "ValorMulta": "0",
                "ValorCalculado": str(r.coverage_value),
                "Vencimentos": []
            })

    if r.account_document or r.account_name or r.account_bank or r.account_agency or r.account_number:
        cpf_cnpj_raw = r.account_document or r.insured_document
        cpf_cnpj = str(cpf_cnpj_raw) if cpf_cnpj_raw is not None else None
        if cpf_cnpj and cpf_cnpj not in rows_by_contract[contract_key]["account_cpf_set"]:
            rows_by_contract[contract_key]["account_cpf_set"].add(cpf_cnpj)
            rows_by_contract[contract_key]["accounts"].append({
                "CpfCnpj": cpf_cnpj,
                "Nome": r.account_name or r.insured_name,
                "SocialName": None,
                "ContaBancaria": {
                    "CodigoBanco": int(r.account_bank or 0),
                    "Agencia": r.account_agency or "0000",
                    "NumeroConta": r.account_number or "00000000",
                    "TipoConta": 0
                }
            })

for contract_key, data in rows_by_contract.items():
    r = data["row"]

    if db.AvisoSinistro.find_one({"Sinistros": contract_key}):
        continue

    if not data["coverages"]:
        print(f"Erro: contrato {contract_key} sem coberturas.")
        continue

    apolice_coberturas = []
    missing_cobertura = False
    for cov in data["coverages"]:
        cob = cobertura_integrada(cov["IdCobertura"])
        if not cob:
            print(
                f"Erro: cobertura não encontrada para contrato {contract_key} e cobertura {cov['IdCobertura']}."
            )
            missing_cobertura = True
            break
        apolice_coberturas.append(cob)

    if missing_cobertura:
        continue
    now = datetime.now()

    beneficiarios = data["accounts"] or [{
        "CpfCnpj": str(r.insured_document) if r.insured_document is not None else None,
        "Nome": r.insured_name,
        "SocialName": None,
        "ContaBancaria": {
            "CodigoBanco": 0,
            "Agencia": "0000",
            "NumeroConta": "00000000",
            "TipoConta": 0
        }
    }]

    doc = {
        "Sinistros": [contract_key],
        "Ocorrencia": to_datetime(r.occurrenceDate),
        "Segurado": {"CpfCnpj": r.insured_document, "DataNascimento": None, "Nome": r.insured_name, "SocialName": None},
        "Reclamante": {"AceitaComunicacao": False, "TipoComunicacao": 0, "Email": r.broker_email, "Telefone": r.broker_phone, "ProprioSegurado": False, "CpfCnpj": r.broker_document, "Nome": r.broker_name, "SocialName": None, "Genero": None, "Endereco": None, "Relacao": 14},
        "Sinistrado": {"CpfCnpj": r.insured_document, "Nome": r.insured_name, "SocialName": None},
        "Beneficiarios": beneficiarios,
        "InformacoesComplementares": {"contactName": r.broker_name, "contactPhone": r.broker_phone, "totalEmail": 1, "contactEmail1": r.broker_email, "pending": False, "fila": "Enviado para regulação", "DataProcessedI4pro": now},
        "Criacao": now,
        "Protocolo": protocolo(),
        "Apolices": [{"NumeroApolice": int(r.policyNumber), "Coberturas": apolice_coberturas}],
        "DataDoAviso": to_datetime(r.sendDate),
        "Status": "Aviso de sinistro enviado para fila de regulacao",
        "Ramo": "FiancaLocaticia",
        "FiancaLocaticia": {"CnpjCorretor": r.broker_document, "SituacaoImovel": 1, "AplicarMulta": False, "Coberturas": data["coverages"]},
        "StatusResumido": "Sinistro enviado",
        "DocumentInformation": {"DocumentStatus": 2, "FullDocumentationDate": None, "RentDueDate": None, "ExpectedCompletionDate": None}
    }

    db.AvisoSinistro.insert_one(doc)

sql_conn.close()
mongo.close()
