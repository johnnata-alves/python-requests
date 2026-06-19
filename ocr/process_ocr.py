import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
import requests
from bson import ObjectId
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_CLAIM_ENGINE")
S3_PREFIX = "https://s3-virginia-prd-auditlogprd.s3.us-east-1.amazonaws.com/"

DB_NAME = "ClaimEngine"
COLLECTION = "Attachment"

API_URL = "http://localhost:5181/api/v1/typification/intake"
TENANT_ID = "11"

FILES_PER_TYPE = 3
MAX_WORKERS = 10
RETRY_COUNT = 3

OUTPUT_CSV = "resultado_typification.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

logger.info("Conectando no MongoDB")
client = MongoClient(MONGO_URI)
collection = client[DB_NAME][COLLECTION]

logger.info("Carregando CSV existente (se houver)")

existing_df = None
existing_keys = set()
existing_ids = set()
existing_types = set()

if Path(OUTPUT_CSV).exists():
    existing_df = pd.read_csv(OUTPUT_CSV, dtype=str)
    if "key" in existing_df.columns:
        existing_keys = set(existing_df["key"].dropna().tolist())
    if "_id" in existing_df.columns:
        existing_ids = set(existing_df["_id"].dropna().tolist())
    if "tipo" in existing_df.columns:
        existing_types = set(existing_df["tipo"].dropna().tolist())

logger.info(
    "CSV existente: %s registros, %s tipos, %s chaves",
    0 if existing_df is None else len(existing_df),
    len(existing_types),
    len(existing_keys),
)

existing_object_ids = []
for value in existing_ids:
    try:
        existing_object_ids.append(ObjectId(value))
    except Exception:
        continue

logger.info("Buscando anexos via aggregation")

def build_pipeline(exclude_processed_types, extra_excluded_types):
    base_match = {"metadata.Key": "tipo_documento"}

    if existing_keys:
        base_match["key"] = {"$nin": list(existing_keys)}
    if existing_object_ids:
        base_match["_id"] = {"$nin": existing_object_ids}

    pipeline = [
        {"$match": base_match},
        {
            "$addFields": {
                "tipo_documento": {
                    "$first": {
                        "$map": {
                            "input": {
                                "$filter": {
                                    "input": "$metadata",
                                    "as": "m",
                                    "cond": {"$eq": ["$$m.Key", "tipo_documento"]},
                                }
                            },
                            "as": "f",
                            "in": "$$f.Value",
                        }
                    }
                }
            }
        },
        {"$match": {"tipo_documento": {"$ne": None}}},
    ]

    tipo_exclusions = set(extra_excluded_types)
    if exclude_processed_types:
        tipo_exclusions |= existing_types

    if tipo_exclusions:
        pipeline.append({"$match": {"tipo_documento": {"$nin": list(tipo_exclusions)}}})

    pipeline.extend(
        [
            {
                "$group": {
                    "_id": "$tipo_documento",
                    "docs": {"$push": "$$ROOT"},
                }
            },
            {
                "$project": {
                    "docs": {"$slice": ["$docs", FILES_PER_TYPE]},
                }
            },
        ]
    )

    return pipeline

documents = []
selected_types = set()

for exclude_processed in (True, False):
    groups = list(collection.aggregate(build_pipeline(exclude_processed, selected_types)))

    for group in groups:
        tipo = group.get("_id")
        if not tipo or tipo in selected_types:
            continue

        for doc in group.get("docs", []):
            documents.append(
                {
                    "tipo": tipo,
                    "key": doc.get("key"),
                    "_id": str(doc.get("_id")),
                }
            )

        selected_types.add(tipo)

logger.info(
    "%s documentos selecionados (%s tipos unicos, ate %s por tipo)",
    len(documents),
    len(selected_types),
    FILES_PER_TYPE,
)

def call_api(document):
    key = document["key"]

    if not key:
        return {**document, "status": "missing_key", "success": False}

    s3_path = key.replace(S3_PREFIX, "") if key.startswith(S3_PREFIX) else key
    correlation_id = str(uuid.uuid4())

    payload = {
        "tenant_id": TENANT_ID,
        "s3_path": s3_path,
        "correlation_id": correlation_id,
        "origin": "load_test",
    }

    for attempt in range(RETRY_COUNT):
        try:
            response = requests.post(API_URL, json=payload, timeout=30)
            return {
                **document,
                "s3_path": s3_path,
                "correlation_id": correlation_id,
                "status_code": response.status_code,
                "success": response.status_code < 300,
                "attempt": attempt + 1,
            }
        except Exception as exc:
            if attempt == RETRY_COUNT - 1:
                return {
                    **document,
                    "s3_path": s3_path,
                    "correlation_id": correlation_id,
                    "success": False,
                    "attempt": attempt + 1,
                    "error": str(exc),
                }

    return {
        **document,
        "s3_path": s3_path,
        "correlation_id": correlation_id,
        "success": False,
        "error": "unexpected_retry_flow",
    }

logger.info("Iniciando chamadas na API")
results = []

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = [executor.submit(call_api, document) for document in documents]

    for future in tqdm(as_completed(futures), total=len(futures)):
        results.append(future.result())

logger.info("Chamadas finalizadas")

df_new = pd.DataFrame(results)
df_new["timestamp"] = datetime.utcnow()

if existing_df is not None and not existing_df.empty:
    df_out = pd.concat([existing_df, df_new], ignore_index=True)
else:
    df_out = df_new

df_out.to_csv(OUTPUT_CSV, index=False)

logger.info("Resultado salvo em %s", OUTPUT_CSV)
