import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Tuple

import pyodbc
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne
from tqdm import tqdm

load_dotenv()

STATUS_PENDENTE = "Pendente geração de certificado"
STATUS_SEM_TEMPLATE = "Sem TemplateId"
STATUS_FORA_CORTE = "Fora do corte"

DATA_CORTE = {
    "262": datetime(2025, 11, 13),
    "317": datetime(2025, 11, 17),
    "381": datetime(2025, 11, 17),
    "218": datetime(2025, 12, 1),
    "274": datetime(2025, 12, 1),
    "246": datetime(2025, 12, 4),
    "389": datetime(2025, 12, 4),
    "342": datetime(2025, 12, 5),
    "325": datetime(2025, 12, 5),
    "365": datetime(2025, 12, 8),
    "388": datetime(2025, 12, 11),
    "394": datetime(2025, 12, 11),
    "251": datetime(2025, 12, 11),
    "370": datetime(2025, 12, 11),
    "360": datetime(2026, 1, 6),
    "379": datetime(2026, 1, 12),
    "396": datetime(2026, 1, 21),
    "399": datetime(2026, 2, 18),
    "349": datetime(2026, 3, 4),
    "363": datetime(2026, 3, 5),
    "382": datetime(2026, 3, 5),
    "237": datetime(2026, 3, 6),
    "106": datetime(2026, 3, 12),
    "397": datetime(2026, 3, 13),
    "333": datetime(2026, 4, 13),
    "278": datetime(2026, 4, 13),
}

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
SQL_CONN = os.getenv("SQL_CONNECTION_I4PRO_PRD") or os.getenv("SQL_CONNECTION")
MONGO_DB = "testeMigracao"
MONGO_COLLECTION = "MetaColetivo"
DRY_RUN = False
MAX_WORKERS = 8

SQL_QUERY = """
SELECT b.nm_produto, c.cd_apolice, a.CertificateId, BranchId, ProductCode, a.PolicyId
FROM IntegraMeta..CertificateGrouping a WITH(NOLOCK)
INNER JOIN i4Pro_erp..corp_produto b ON a.ProductCode = b.cd_produto
INNER JOIN i4Pro_erp..corp_apolice c ON a.PolicyId = c.id_apolice
WHERE c.cd_apolice = ?
"""

def build_pending_filter(cd_apolice=None) -> dict:
    base = {
        "details.0": {"$exists": True},
        "status": {"$in": [STATUS_PENDENTE, STATUS_SEM_TEMPLATE]},
        "$or": [
            {"details.0.TemplateId": {"$in": ["", None]}},
            {"details.0.TemplateId": {"$exists": False}},
        ],
    }
    if cd_apolice is not None:
        variants = []
        normalized = normalize_key(cd_apolice)

        if normalized:
            variants.append(normalized)

            if normalized.isdigit():
                variants.append(int(normalized))

        if isinstance(cd_apolice, int):
            variants.append(cd_apolice)
            variants.append(str(cd_apolice))

        deduped = list(dict.fromkeys(variants))
        if deduped:
            base["details.0.cd_apolice"] = {"$in": deduped}
    return base

def normalize_key(value) -> str:
    if value is None:
        return ""
    return str(value).strip()

def parse_dt_emissao(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    raw = normalize_key(value)
    if not raw:
        return None

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d%m%Y"):
        try:
            return datetime.strptime(raw[:10], fmt)
        except ValueError:
            continue

    return None

def load_sql_data(conn_str: str, cd_apolice: str) -> Dict[str, List[dict]]:
    """Carrega dados do SQL e agrupa por cd_apolice."""
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    rows = cursor.execute(SQL_QUERY, cd_apolice).fetchall()
    cursor.close()
    conn.close()

    grouped: Dict[str, List[dict]] = {}
    for row in rows:
        cd_apolice_row = normalize_key(row[1])
        entry = {
            "nm_produto": normalize_key(row[0]),
            "cd_apolice": cd_apolice_row,
            "CertificateId": normalize_key(row[2]),
            "BranchId": normalize_key(row[3]),
            "ProductCode": normalize_key(row[4]),
            "PolicyId": normalize_key(row[5]),
        }
        grouped.setdefault(cd_apolice_row, []).append(entry)

    return grouped

def process_apolice(
    mongo_uri: str,
    db_name: str,
    collection_name: str,
    cd_apolice,
    sql_entries: List[dict],
) -> dict:
    """Processa todos os documentos de um cd_apolice de uma vez."""
    client = MongoClient(mongo_uri)
    collection = client[db_name][collection_name]

    sql_map: Dict[Tuple[str, str], str] = {}
    for entry in sql_entries:
        key = (entry["ProductCode"], entry["cd_apolice"])
        if key not in sql_map:
            sql_map[key] = entry["CertificateId"]

    pending_filter = build_pending_filter(cd_apolice)
    docs = list(collection.find(pending_filter, {"_id": 1, "details": 1}))

    operations = []
    matched = 0
    unmatched = 0
    fora_corte = 0

    for doc in docs:
        details = doc.get("details", [])
        if not isinstance(details, list) or not details:
            continue

        detail = details[0] if isinstance(details[0], dict) else {}
        template_id = detail.get("TemplateId")
        if template_id not in ("", None):
            continue

        cd_produto = normalize_key(detail.get("cd_produto"))
        if cd_produto in DATA_CORTE:
            dt_emissao = parse_dt_emissao(detail.get("dt_emissao"))
            if dt_emissao and dt_emissao > DATA_CORTE[cd_produto]:
                fora_corte += 1
                operations.append(
                    UpdateOne(
                        {"_id": doc["_id"]},
                        {"$set": {"status": STATUS_FORA_CORTE}},
                    )
                )
                continue

        key = (
            cd_produto,
            normalize_key(detail.get("cd_apolice")),
        )

        if key in sql_map:
            matched += 1
            operations.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {
                        "$set": {
                            "details.0.TemplateId": sql_map[key],
                        }
                    },
                )
            )
        else:
            unmatched += 1
            operations.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {"$set": {"status": STATUS_SEM_TEMPLATE}},
                )
            )

    modified = 0
    if operations and not DRY_RUN:
        result = collection.bulk_write(operations, ordered=False)
        modified = result.modified_count

    client.close()
    return {
        "cd_apolice": normalize_key(cd_apolice),
        "total_docs": len(docs),
        "matched": matched,
        "unmatched": unmatched,
        "fora_corte": fora_corte,
        "modified": modified,
    }

def main() -> None:
    if not MONGO_URI:
        raise ValueError("Defina PRD_MONGO_SA_EAST.")
    if not SQL_CONN:
        raise ValueError("Defina SQL_CONNECTION_I4PRO_PRD ou SQL_CONNECTION.")

    client = MongoClient(MONGO_URI)
    collection = client[MONGO_DB][MONGO_COLLECTION]
    pending_filter = build_pending_filter()
    apolices = collection.distinct("details.0.cd_apolice", pending_filter)
    client.close()

    apolices = [a for a in apolices if a is not None and normalize_key(a)]
    print(f"Apolices distintas (details.0.cd_apolice) pendentes: {len(apolices)}")

    if not apolices:
        print("Nenhuma apolice pendente. Encerrando.")
        return

    total_matched = 0
    total_unmatched = 0
    total_fora_corte = 0
    total_modified = 0
    total_docs = 0

    print(f"Processando em paralelo ({MAX_WORKERS} workers)...")

    def process_one(cd_apolice) -> dict:
        """Carrega SQL filtrado por cd_apolice e processa os docs."""
        cd_apolice_key = normalize_key(cd_apolice)
        grouped = load_sql_data(SQL_CONN, cd_apolice_key)
        entries = grouped.get(cd_apolice_key, [])
        return process_apolice(
            MONGO_URI,
            MONGO_DB,
            MONGO_COLLECTION,
            cd_apolice,
            entries,
        )

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_one, ap): ap for ap in apolices}

        with tqdm(total=len(futures), desc="Apolices processadas") as pbar:
            for future in as_completed(futures):
                result = future.result()
                total_docs += result["total_docs"]
                total_matched += result["matched"]
                total_unmatched += result["unmatched"]
                total_fora_corte += result["fora_corte"]
                total_modified += result["modified"]
                pbar.update(1)

    print(
        f"\nResumo | "
        f"docs processados: {total_docs} | "
        f"com match: {total_matched} | "
        f"sem match: {total_unmatched} | "
        f"fora do corte: {total_fora_corte} | "
        f"modificados: {total_modified}"
    )

if __name__ == "__main__":
    main()
