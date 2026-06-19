import os
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timezone
from collections import defaultdict
import pandas as pd
import re

load_dotenv()

MONGO_URI = os.getenv("HML_MONGO_URI")

DB_NAME = "ClaimEngine"
COLLECTION = "Attachment"

FILTER_DATE = datetime(2026, 5, 4, 17, 0, 0, tzinfo=timezone.utc)

client = MongoClient(MONGO_URI)
collection = client[DB_NAME][COLLECTION]

query = {
    "status": "Typified",
    "UpdatedAt": {"$gte": FILTER_DATE},
    "documentTypificationCall.response": {"$regex": ".*\"TenantId\":\"25\".*", "$options": "i"}
}

cursor = collection.find(query)

stats = defaultdict(lambda: defaultdict(lambda: {
    "total": 0,
    "filled": 0,
    "valid_total": 0,
    "valid_true": 0
}))

for doc in cursor:
    metadata_list = doc.get("metadata", [])

    for meta in metadata_list:
        doc_type = meta.get("DocumentType")

        for field in meta.get("Fields", []):
            if field.get("Type") != "Required":
                continue

            key = field.get("Key")
            value = field.get("Value")

            stats[doc_type][key]["total"] += 1

            if value not in [None, ""]:
                stats[doc_type][key]["filled"] += 1

            if "Valid" in field:
                stats[doc_type][key]["valid_total"] += 1
                if field.get("Valid") is True:
                    stats[doc_type][key]["valid_true"] += 1

received_stats = {}
quantidade_stats = {}
for doc_type in stats.keys():
    base_filter = {"status": "Typified", "UpdatedAt": {"$gte": FILTER_DATE}, "documentTypificationCall.response": {"$regex": ".*\"TenantId\":\"25\".*", "$options": "i"}, "metadata.DocumentType": doc_type}
    total_docs = collection.count_documents(base_filter)
    received_docs = collection.count_documents({**base_filter, "metadataValidationSuccess": True})
    pct_received = (received_docs / total_docs) * 100 if total_docs > 0 else 0
    received_stats[doc_type] = round(pct_received, 2)
    quantidade_stats[doc_type] = total_docs

rows = []

for doc_type, fields in stats.items():
    for key, data in fields.items():
        total = data["total"]
        filled = data["filled"]

        pct_filled = (filled / total) * 100 if total > 0 else 0

        if data["valid_total"] > 0:
            pct_valid = (data["valid_true"] / data["valid_total"]) * 100
        else:
            pct_valid = None

        rows.append({
            "DocumentType": doc_type,
            "Quantidade": quantidade_stats.get(doc_type, 0),
            "Key": key,
            "%_recebimento": round(pct_filled, 2),
            "%_valido": round(pct_valid, 2) if pct_valid is not None else None,
            "Received": received_stats.get(doc_type, 0)
        })

df = pd.DataFrame(rows)

if not df.empty and all(col in df.columns for col in ["DocumentType", "Key"]):
    df = df.sort_values(by=["DocumentType", "Key"])
else:
    print("[AVISO] DataFrame vazio ou colunas ausentes. Não foi possível ordenar.")

query_all = {
    "status": "Typified",
    "UpdatedAt": {"$gte": FILTER_DATE},
    "documentTypificationCall.response": {"$regex": ".*\"TenantId\":\"25\".*", "$options": "i"}
}
cursor_all = collection.find(query_all)
rows_all = []

def ajustar_filename(nome):
    if not nome:
        return ""
    match = re.match(r"^[^_]+_([^_]+_.*)_([a-f0-9]{32,})\.(\w+)$", nome)
    if match:
        base = match.group(1)
        ext = match.group(3)
        base = re.sub(r'_[a-f0-9]{8,}$', '', base)
        return f"{base}.{ext}"
    partes = nome.split('_')
    if len(partes) > 2:
        return '_'.join(partes[1:-1]) + '.' + nome.split('.')[-1]
    return nome

for doc in cursor_all:
    protocolo = doc.get("protocol") or doc.get("protocolNumber") or doc.get("_id")
    file_name = doc.get("fileName")
    file_name_ajustado = ajustar_filename(file_name)
    updated_at = doc.get("UpdatedAt")
    metadata_list = doc.get("metadata", [])
    for meta in metadata_list:
        doc_type = meta.get("DocumentType")
        for field in meta.get("Fields", []):
            if field.get("Type") != "Required":
                continue
            key = field.get("Key")
            value = field.get("Value")
            valido = field.get("Valid") if "Valid" in field else None
            recebido = value not in [None, ""]
            rows_all.append({
                "Protocolo": protocolo,
                "fileName": file_name_ajustado,
                "DocumentType": doc_type,
                "Key": key,
                "Value": value,
                "Recebido": recebido,
                "Valido": valido,
                "UpdatedAt": updated_at
            })

df_all = pd.DataFrame(rows_all)

now = datetime.now().strftime("%Y%m%d_%H%M")
output_file = f"relatorio_metadados_{now}.xlsx"
with pd.ExcelWriter(output_file) as writer:
    df.to_excel(writer, index=False, sheet_name="Resumo")
    df_all.to_excel(writer, index=False, sheet_name="Detalhado")

    resumo_rows = []
    for doc_type in stats.keys():
        fields = stats[doc_type]
        total_campos = 0
        total_recebidos = 0
        total_validos = 0
        total_validaveis = 0
        for key, data in fields.items():
            total_campos += data["total"]
            total_recebidos += data["filled"]
            total_validos += data["valid_true"]
            total_validaveis += data["valid_total"]
        pct_total_metadados = (total_recebidos / total_campos) * 100 if total_campos > 0 else 0
        pct_valido = (total_validos / total_validaveis) * 100 if total_validaveis > 0 else 0
        pct_recebido = received_stats.get(doc_type, 0)
        resumo_rows.append({
            "DocumentType": doc_type,
            "% total de metadados": round(pct_total_metadados, 2),
            "%Recebido": round(pct_recebido, 2),
            "%Valido": round(pct_valido, 2)
        })
    df_resumo_tipo = pd.DataFrame(resumo_rows)
    df_resumo_tipo.to_excel(writer, index=False, sheet_name="ResumoPorTipo")

print(df.head())
print(df_all.head())

client.close()
