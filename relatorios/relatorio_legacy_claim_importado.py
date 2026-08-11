"""
Busca LegacyAttachment desde 23/06,
pega LegacyClaim com status "Importado",
consulta SQL em lotes de 100 para status/cancelamento/pagamento,
classifica regulado se tem evento 10105 ou 11001,
exporta Excel com dados da LegacyClaim + SQL + data ultimo anexo.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import pyodbc
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
DB_NAME = "ClaimEngine"
SQL_CONNECTION = os.getenv("SQL_CONNECTION_I4PRO_PRD")
WORKERS = 8
BATCH_SIZE = 100

SQL_QUERY_TEMPLATE = """
SELECT
    a.nr_sinistro,
    b.nm_status AS status_processo,
    c.nm_status AS status_movimento,
    d.dt_sistema AS dt_cancelamento,
    f.nm_motivo AS motivo_cancelamento,
    e.dt_sistema AS dt_pagamento
FROM corp_sinistro a
INNER JOIN corp_status b ON a.cd_status = b.cd_status
INNER JOIN corp_status c ON a.cd_status_movimento = c.cd_status
OUTER APPLY (
    SELECT TOP (1) *
    FROM corp_sin_movto sm
    WHERE sm.nr_sinistro = a.nr_sinistro AND sm.cd_evento = 10105
    ORDER BY sm.dt_sistema DESC
) d
OUTER APPLY (
    SELECT TOP (1) *
    FROM corp_sin_movto sm
    WHERE sm.nr_sinistro = a.nr_sinistro AND sm.cd_evento = 11001
    ORDER BY sm.dt_sistema DESC
) e
LEFT JOIN corp_tp_motivo f ON d.id_tp_motivo = f.id_tp_motivo
WHERE a.nr_sinistro IN ({placeholders})
"""

lock = threading.Lock()


def buscar_sql_lote(sinistros):
    """Consulta SQL em lote, retorna dict nr_sinistro -> dados."""
    if not sinistros:
        return {}

    placeholders = ",".join(["?"] * len(sinistros))
    query = SQL_QUERY_TEMPLATE.format(placeholders=placeholders)

    conn = pyodbc.connect(SQL_CONNECTION)
    cursor = conn.cursor()
    cursor.execute(query, sinistros)

    resultado = {}
    for row in cursor.fetchall():
        resultado[row.nr_sinistro] = {
            "status_processo": row.status_processo,
            "status_movimento": row.status_movimento,
            "dt_cancelamento": row.dt_cancelamento,
            "motivo_cancelamento": row.motivo_cancelamento,
            "dt_pagamento": row.dt_pagamento,
            "regulado": row.dt_cancelamento is not None or row.dt_pagamento is not None,
        }

    cursor.close()
    conn.close()
    return resultado


def get_ultimo_anexo_batch(protocolos):
    """Busca maior CreatedAt do LegacyAttachment para cada protocolo."""
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    resultado = {}
    pipeline = [
        {"$match": {"protocol": {"$in": list(protocolos)}}},
        {"$group": {"_id": "$protocol", "maxCreatedAt": {"$max": "$CreatedAt"}}}
    ]
    for doc in db["LegacyAttachment"].aggregate(pipeline):
        resultado[doc["_id"]] = doc["maxCreatedAt"]

    client.close()
    return resultado


def main():
    if not SQL_CONNECTION:
        print("ERRO: SQL_CONNECTION_I4PRO_PRD_V2 não configurada no .env")
        return

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    data_limite = datetime(2026, 6, 23)

    print(f"Buscando LegacyAttachment com CreatedAt >= {data_limite.isoformat()}...")

    total_attachments = db["LegacyAttachment"].count_documents({"CreatedAt": {"$gte": data_limite}})
    attachments = db["LegacyAttachment"].find(
        {"CreatedAt": {"$gte": data_limite}},
        {"protocol": 1}
    )

    protocolos = set()
    for att in tqdm(attachments, total=total_attachments, desc="Buscando protocolos", unit="doc"):
        proto = att.get("protocol")
        if proto:
            protocolos.add(proto)

    print(f"Protocolos únicos: {len(protocolos)}")

    # Buscar LegacyClaim com status Importado
    claims = list(db["LegacyClaim"].find({
        "protocol": {"$in": list(protocolos)},
        "status": "Importado"
    }))

    client.close()

    print(f"LegacyClaim com status 'Importado': {len(claims)}")

    if not claims:
        print("Nada para processar.")
        return

    # Buscar data ultimo anexo em batch
    print("Buscando data último anexo...")
    protocolo_list = list({c.get("protocol") for c in claims if c.get("protocol")})
    anexo_map = {}
    for i in range(0, len(protocolo_list), 500):
        batch = protocolo_list[i:i+500]
        anexo_map.update(get_ultimo_anexo_batch(batch))

    # Consultar SQL em lotes de 100
    claim_numbers = [c.get("claimNumber") for c in claims if c.get("claimNumber")]
    sql_map = {}

    print("Consultando SQL em lotes...")
    for i in tqdm(range(0, len(claim_numbers), BATCH_SIZE), desc="SQL lotes", unit="lote"):
        batch = claim_numbers[i:i+BATCH_SIZE]
        sql_map.update(buscar_sql_lote(batch))

    # Montar resultados
    resultados = []
    for claim in claims:
        claim_number = claim.get("claimNumber")
        protocol = claim.get("protocol", "")
        insured = claim.get("insured") or {}

        sql_data = sql_map.get(claim_number, {})

        row = {
            "claimNumber": claim_number,
            "protocol": protocol,
            "statusLegacyClaim": claim.get("status", ""),
            "productName": claim.get("productName", ""),
            "product": claim.get("product", ""),
            "policyNumber": claim.get("policyNumber", ""),
            "coverage": claim.get("coverage", ""),
            "causeType": claim.get("causeType", ""),
            "step": claim.get("step", ""),
            "regulatoryStatusName": claim.get("regulatoryStatusName", ""),
            "regulatoryStatusCode": claim.get("regulatoryStatusCode", ""),
            "insuredName": insured.get("name", ""),
            "insuredDocument": insured.get("documentNumber", ""),
            "occurrenceDate": claim.get("occurrenceDate", ""),
            "notificationDate": claim.get("notificationDate", ""),
            "notificationOrigin": claim.get("notificationOrigin", ""),
            "dataUltimoAnexo": anexo_map.get(protocol, ""),
            "regulado": sql_data.get("regulado", False),
            "nomeStatusProcesso": sql_data.get("status_processo", ""),
            "nomeStatusMovimento": sql_data.get("status_movimento", ""),
            "dt_cancelamento": sql_data.get("dt_cancelamento", ""),
            "motivoCancelamento": sql_data.get("motivo_cancelamento", ""),
            "dt_pagamento": sql_data.get("dt_pagamento", ""),
        }
        resultados.append(row)

    # Exportar Excel
    df = pd.DataFrame(resultados)

    columns_order = [
        "claimNumber",
        "protocol",
        "statusLegacyClaim",
        "productName",
        "product",
        "policyNumber",
        "coverage",
        "causeType",
        "step",
        "regulatoryStatusName",
        "regulatoryStatusCode",
        "insuredName",
        "insuredDocument",
        "occurrenceDate",
        "notificationDate",
        "notificationOrigin",
        "dataUltimoAnexo",
        "regulado",
        "nomeStatusProcesso",
        "nomeStatusMovimento",
        "dt_cancelamento",
        "motivoCancelamento",
        "dt_pagamento",
    ]
    df = df.reindex(columns=columns_order)

    output_file = f"relatorio_legacy_claim_importado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(output_file, index=False, engine="openpyxl")

    regulados = df[df["regulado"] == True]

    print(f"\nFinalizado!")
    print(f"  Total claims: {len(claims)}")
    print(f"  Regulados (10105/11001): {len(regulados)}")
    print(f"  Excel: {output_file}")


if __name__ == "__main__":
    main()
