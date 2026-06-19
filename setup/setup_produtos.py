import os
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime
from pymongo import MongoClient

load_dotenv()

EXCEL_FILE = "setup_produtos.xlsx"
MAIN_SHEET = "setup"
TP_CAUSA_SHEET = "tp_causa"

MONGO_URI = os.getenv("HML_MONGO_URI")
MONGO_DB_NAME = "ProductEngine"
MONGO_COLLECTION_NAME = "productClaim_Setup"

CREATED_USER_NAME = "Johnnata Alves"
UPDATED_USER_NAME = "Johnnata Alves"

ALLOWED_STATUSES_IDS = [
    848, 816, 815, 808, 804, 803, 801, 491, 490, 480, 478, 477, 473, 472,
    471, 469, 468, 467, 466, 463, 462, 459, 458, 457, 456, 455, 454, 453,
    450, 449, 448, 447, 426, 421, 416, 162, 161,
    11052, 10094, 10092, 10091, 10090, 10089, 10088, 10087, 10084, 10083,
    10082, 10081
]

ALLOWED_MOVEMENTS_IDS = [
    10105, 10104, 10102, 11001, 10103
]

ALLOWED_FOLLOW_TYPES_IDS = [
    97, 96, 95, 93, 92, 90, 89, 88, 87, 86, 85, 83, 79, 78, 77, 76, 74,
    73, 71, 70, 67, 66, 58, 57, 56, 54, 53, 52, 51, 50, 49, 45, 43, 42,
    41, 40, 37, 3, 29, 26, 21, 20, 2, 169, 168, 167, 166, 165, 164, 163,
    162, 161, 160, 159, 158, 157, 156, 155, 154, 153, 151, 150, 148, 137,
    133, 132, 131, 130, 13, 129, 128, 1270040, 1270002, 127, 126, 125,
    124, 123, 122, 121, 120, 119, 118, 117, 116, 115, 114, 113, 112, 111,
    110, 11, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100
]

REFUSED_REASONS_TEMPLATE = [
    {
        "refusedReasonCode": 11,
        "defaultFollow": (
            "Sinistro cancelado por CARENCIA. Data de ocorrencia: {dataSinistro} "
            "||  Data de Comunicação: {dataComunicacao}"
        ),
        "followUpTypeCode": 3,
        "claimInformationType": "string"
    },
    {
        "refusedReasonCode": 44,
        "defaultFollow": (
            "Sinistro cancelado por estar FORA DA VIGENCIA da apolice. "
            "Data de ocorrencia: {dataSinistro} ||  Data de Comunicação: {dataComunicacao}"
        ),
        "followUpTypeCode": 3,
        "claimInformationType": "string"
    },
    {
        "refusedReasonCode": 45,
        "defaultFollow": (
            "Sinistro cancelado por estar dentro da FRANQUIA da apolice. "
            "Data de ocorrencia: {dataSinistro} ||  Data de Comunicação: {dataComunicacao}"
        ),
        "followUpTypeCode": 3,
        "claimInformationType": "string"
    },
    {
        "refusedReasonCode": 55,
        "defaultFollow": (
            "Sinistro cancelado por passar do prazo legal PRESCRIÇÃO. "
            "Data de ocorrencia: {dataSinistro} ||  Data de Comunicação: {dataComunicacao}"
        ),
        "followUpTypeCode": 3,
        "claimInformationType": "string"
    }
]

COMMUNICATIONS_TEMPLATE = [
    "claim.regulation.claim-engine.communication.claim.created",
    "claim.regulation.claim-engine.communication.claim.status-updated",
    "claim.regulation.claim-engine.communication.claim.canceled",
    "claim.regulation.claim-engine.communication.claim.pending",
    "claim.regulation.claim-engine.communication.claim.pending-reiteration",
    "claim.regulation.claim-engine.communication.document.typified",
    "claim.regulation.claim-engine.communication.notification.document-received"
]

BENEFICIARY_TYPES_TEMPLATE = [
    "HEIRS", "STIPULATOR"
]

STIPULATOR_TEMPLATE = {
    "beneficiary": {
        "personCode": 308186,
        "percentage": 50,
        "relationshipCode": 3,
        "relationshipType": "Beneficiary",
        "justification": (
            "CADASTRO AUTOMATICO DE BENEFICIARIO POR SER DO TIPO ESTIPULANTE"
        )
    }
}

def get_steps_template():
    """Retorna o objeto steps igual ao do exemplo."""
    return {
        "preRegulation": [
            {
                "order": 1,
                "sla": 1,
                "name": "STARTED",
                "code": "STARTED",
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            },
            {
                "order": 2,
                "sla": 1,
                "name": "VALIDATION",
                "code": "VALIDATION",
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            },
            {
                "order": 3,
                "sla": 1,
                "name": "WAIT_DOCUMENTATION",
                "code": "WAIT_DOCUMENTATION",
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            },
            {
                "order": 4,
                "sla": 1,
                "name": "REVIEW",
                "code": "REVIEW",
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            },
            {
                "order": 5,
                "sla": 1,
                "name": "CONCLUSION",
                "code": "CONCLUSION",
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            }
        ],
        "regulation": [
            {
                "order": 1,
                "sla": 1,
                "name": "PRE_REGULATION",
                "code": "PRE_REGULATION",
                "hasLetter": False,
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            },
            {
                "order": 2,
                "sla": 1,
                "name": "REGULATION",
                "code": "REGULATION",
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            },
            {
                "order": 3,
                "sla": 1,
                "name": "DECISION",
                "code": "DECISION",
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            },
            {
                "order": 5,
                "sla": 1,
                "name": "BENEFICIARIES_INCLUSION",
                "code": "BENEFICIARIES_INCLUSION",
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            },
            {
                "order": 4,
                "sla": 1,
                "name": "PAYMENT",
                "code": "PAYMENT",
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            },
            {
                "order": 6,
                "sla": 1,
                "name": "CONCLUSION",
                "code": "CONCLUSION",
                "rules": [
                    "PERMITE_RESIDUO_IS",
                    "CHECAR_CARENCIA",
                    "REGRA_ETC"
                ]
            }
        ]
    }

def to_int_or_none(value):
    if pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def build_allowed_cause_ids_map(tp_causa_df):
    """
    Monta um dicionário:
    id_ramo (int) -> lista de cd_causa (int)
    com base na aba tp_causa.
    """
    mapping = {}
    if tp_causa_df is None or tp_causa_df.empty:
        return mapping

    assert "id_ramo" in tp_causa_df.columns, "Coluna 'id_ramo' não encontrada em tp_causa"
    assert "cd_causa" in tp_causa_df.columns, "Coluna 'cd_causa' não encontrada em tp_causa"

    grouped = tp_causa_df.groupby("id_ramo")
    for id_ramo, group in grouped:
        id_ramo_int = to_int_or_none(id_ramo)
        if id_ramo_int is None:
            continue
        causas = sorted(
            {
                to_int_or_none(v)
                for v in group["cd_causa"].dropna().unique()
                if to_int_or_none(v) is not None
            }
        )
        mapping[id_ramo_int] = causas
    return mapping

def build_coverage_docs(coverage_df):
    """
    Monta o array 'documentation' para uma cobertura,
    garantindo que não haja documentos com erpDocumentId repetido.
    """
    docs = []
    seen_erp_ids = set()

    for _, row in coverage_df.iterrows():
        nm_documento = row.get("nm_documento")
        erp_doc = row.get("doc")

        if pd.isna(nm_documento) and pd.isna(erp_doc):
            continue

        erp_id = to_int_or_none(erp_doc)

        if erp_id is not None and erp_id in seen_erp_ids:
            continue

        if erp_id is not None:
            seen_erp_ids.add(erp_id)

        doc_obj = {
            "type": None if pd.isna(nm_documento) else str(nm_documento),
            "documentTypeIds": [],
            "requiresDataValidation": False,
            "isRequired": True,
            "isInsuredDocument": True,
            "isBeneficiaryDocument": False,
            "isActive": True,
            "erpDocumentId": erp_id,
            "metadata": ["string"],
            "relatedErpDocumentIds": [],
            "autoRequiredDocumentIds": []
        }
        docs.append(doc_obj)

    return docs

def build_coverages(group_df):
    """
    Monta o array de 'coverages' para um grupo de linhas
    de um mesmo produto (mesma susep).
    """
    coverages = []

    coverage_group_cols = [
        "Cobertura",
        "nm_cobertura",
        "Grupo_cobertura",
        "cd_causa",
        "nm_tp_causa"
    ]

    for col in coverage_group_cols:
        if col not in group_df.columns:
            raise ValueError(f"Coluna '{col}' não encontrada na planilha principal")

    grouped = group_df.groupby(coverage_group_cols, dropna=False)

    for (coverage_id, coverage_name, coverage_group_id,
         cause_type_id, cause_type), cov_df in grouped:

        coverage_obj = {
            "coverageId": to_int_or_none(coverage_id),
            "coverageName": None if pd.isna(coverage_name) else str(coverage_name),
            "coverageGroupId": to_int_or_none(coverage_group_id),
            "causeTypeId": to_int_or_none(cause_type_id),
            "causeType": None if pd.isna(cause_type) else str(cause_type),
            "active": True,
            "documentation": build_coverage_docs(cov_df),
            "steps": get_steps_template(),
            "totalRegulatoryTime": {
                "type": "DAY",
                "value": 14
            },
            "notificationPendingDeadLine": {
                "type": "DAY",
                "value": 30
            },
            "regulationPendingDeadLine": {
                "type": "DAY",
                "value": 30
            },
            "refusedReasons": REFUSED_REASONS_TEMPLATE,
            "communications": COMMUNICATIONS_TEMPLATE,
            "beneficiaryTypes": BENEFICIARY_TYPES_TEMPLATE
        }

        coverages.append(coverage_obj)

    return coverages

def build_product_document(susep, group_df, allowed_cause_map):
    """
    Monta o documento final do produto (por susep) no formato esperado.
    """
    if "cd_produto" not in group_df.columns:
        raise ValueError("Coluna 'cd_produto' não encontrada na planilha principal")

    erp_ids = sorted({
        to_int_or_none(v)
        for v in group_df["cd_produto"].dropna().unique()
        if to_int_or_none(v) is not None
    })

    if "nm_produto" not in group_df.columns:
        raise ValueError("Coluna 'nm_produto' não encontrada na planilha principal")

    nm_produto_series = group_df["nm_produto"].dropna()
    susep_product_name = str(nm_produto_series.iloc[0]) if not nm_produto_series.empty else None

    if "ramo" not in group_df.columns:
        raise ValueError("Coluna 'ramo' não encontrada na planilha principal")
    if "id_ramo" not in group_df.columns:
        raise ValueError("Coluna 'id_ramo' não encontrada na planilha principal")

    ramo_series = group_df["ramo"].dropna()
    branch = str(ramo_series.iloc[0]) if not ramo_series.empty else None

    id_ramo_series = group_df["id_ramo"].dropna()
    branch_id = to_int_or_none(id_ramo_series.iloc[0]) if not id_ramo_series.empty else None

    if branch_id is not None:
        allowed_cause_ids = allowed_cause_map.get(branch_id, [])
    else:
        allowed_cause_ids = []

    coverages = build_coverages(group_df)

    now = datetime.utcnow()

    product_doc = {
        "susepProductNumber": str(susep) if susep is not None else None,
        "erpProductIds": erp_ids,
        "susepProductName": susep_product_name,
        "active": True,
        "allowedStatusesIds": ALLOWED_STATUSES_IDS,
        "allowedMovementsIds": ALLOWED_MOVEMENTS_IDS,
        "allowedCauseClassificationTypesIds": allowed_cause_ids,
        "allowedFollowTypesIds": ALLOWED_FOLLOW_TYPES_IDS,
        "branch": branch,
        "branchId": branch_id,
        "coverages": coverages,
        "createdAt": now,
        "updatedAt": now,
        "createdUserName": CREATED_USER_NAME,
        "updatedUserName": UPDATED_USER_NAME,
        "stipulator": STIPULATOR_TEMPLATE
    }

    return product_doc

def main():
    print("Lendo planilha Excel...")
    df_main = pd.read_excel(EXCEL_FILE, sheet_name=MAIN_SHEET)

    try:
        df_tp_causa = pd.read_excel(EXCEL_FILE, sheet_name=TP_CAUSA_SHEET)
    except ValueError:
        df_tp_causa = pd.DataFrame()

    allowed_cause_map = build_allowed_cause_ids_map(df_tp_causa)

    print("Conectando ao MongoDB...")
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]
    collection = db[MONGO_COLLECTION_NAME]

    if "susep" not in df_main.columns:
        raise ValueError("Coluna 'susep' não encontrada na aba principal da planilha")

    grouped_by_susep = df_main.groupby("susep", dropna=False)

    count = 0
    for susep, group in grouped_by_susep:
        product_doc = build_product_document(susep, group, allowed_cause_map)

        result = collection.update_one(
            {"susepProductNumber": product_doc["susepProductNumber"]},
            {"$set": product_doc},
            upsert=True
        )

        count += 1
        print(
            f"Processado SUSEP: {susep} - upsert: "
            f"matched={result.matched_count}, "
            f"modified={result.modified_count}, "
            f"upserted_id={result.upserted_id}"
        )

    print(f"Concluído. {count} produtos processados.")

if __name__ == "__main__":
    main()
