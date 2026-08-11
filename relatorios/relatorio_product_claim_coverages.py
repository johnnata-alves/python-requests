import os
from dotenv import load_dotenv
from pymongo import MongoClient
import pyodbc
import pandas as pd

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SUBSCRICAO")
MONGO_DB = "ProductEngine"
MONGO_COLLECTION = "productClaim"

SQL_CONNECTION = os.getenv("SQL_CONNECTION_I4PRO_PRD")

SQL_QUERY = """
SELECT DISTINCT
    c.nm_ramo,
    c.nr_ramo,
    a.nm_produto,
    a.cd_produto
FROM corp_produto a
INNER JOIN corp_apolice b ON a.cd_produto = b.cd_produto
INNER JOIN corp_ramo c ON b.id_ramo = c.id_ramo
WHERE a.cd_produto = ?
"""


def get_mongo_data():
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    collection = db[MONGO_COLLECTION]

    rows = []
    for doc in collection.find({"active": True}):
        susep_number = doc.get("susepProductNumber", "")
        susep_name = doc.get("susepProductName", "")
        coverages = doc.get("coverages", [])

        for cov in coverages:
            product = cov.get("product")
            coverage_id = cov.get("coverageId")
            coverage_group_id = cov.get("coverageGroupId")
            coverage_name = cov.get("coverageName")
            cause_type_id = cov.get("causeTypeId")
            documentation = cov.get("documentation", [])

            for doc_item in documentation:
                rows.append({
                    "coverages.product": product,
                    "susepProductNumber": susep_number,
                    "susepProductName": susep_name,
                    "coverageId": coverage_id,
                    "coverageGroupId": coverage_group_id,
                    "coverageName": coverage_name,
                    "causeTypeId": cause_type_id,
                    "causeType": cov.get("causeType"),
                    "erpDocumentId": doc_item.get("erpDocumentId"),
                    "documentType": doc_item.get("type"),
                    "isInsuredDocument": doc_item.get("isInsuredDocument"),
                    "isActive": doc_item.get("isActive"),
                    "isRequired": doc_item.get("isRequired"),
                })

    client.close()
    return rows


def enrich_with_sql(rows):
    if not SQL_CONNECTION:
        print("ERRO: SQL_CONNECTION_I4PRO_PRD_V2 não configurada no .env")
        return rows

    conn = pyodbc.connect(SQL_CONNECTION)
    cursor = conn.cursor()

    cache = {}

    for row in rows:
        product_id = row.get("coverages.product")
        if product_id is None:
            continue

        if product_id not in cache:
            cursor.execute(SQL_QUERY, product_id)
            result = cursor.fetchone()
            if result:
                cache[product_id] = {
                    "nm_ramo": result.nm_ramo,
                    "nr_ramo": result.nr_ramo,
                    "nm_produto": result.nm_produto,
                }
            else:
                cache[product_id] = {
                    "nm_ramo": None,
                    "nr_ramo": None,
                    "nm_produto": None,
                }

        sql_data = cache[product_id]
        row["nm_ramo"] = sql_data["nm_ramo"]
        row["nr_ramo"] = sql_data["nr_ramo"]
        row["nm_produto"] = sql_data["nm_produto"]

    cursor.close()
    conn.close()
    return rows


def main():
    print("Buscando dados do MongoDB...")
    rows = get_mongo_data()
    print(f"Total de linhas extraídas: {len(rows)}")

    print("Enriquecendo com dados SQL...")
    rows = enrich_with_sql(rows)

    df = pd.DataFrame(rows)

    columns_order = [
        "coverages.product",
        "nm_produto",
        "nm_ramo",
        "nr_ramo",
        "susepProductNumber",
        "susepProductName",
        "coverageId",
        "coverageGroupId",
        "coverageName",
        "causeTypeId",
        "causeType",
        "erpDocumentId",
        "documentType",
        "isInsuredDocument",
        "isActive",
        "isRequired",
    ]
    df = df.reindex(columns=columns_order)

    output_file = "relatorio_product_claim_coverages.xlsx"
    df.to_excel(output_file, index=False, engine="openpyxl")
    print(f"Relatório gerado: {output_file}")


if __name__ == "__main__":
    main()
