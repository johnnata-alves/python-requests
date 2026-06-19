import os

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId

load_dotenv()

EXCEL_FILE = "setup_produtos.xlsx"
SHEET_NAME = 0
MONGO_URI = os.getenv("HML_MONGO_URI")
MONGO_DB = "ProductEngine"
MONGO_COLLECTION = "productClaim_BKP"

STATIC_DOC = {
    "active": True,
    "allowedStatusesIds": [10083,848,455,421,477,10090,447,426,10084,801,804,453,450,10081,454,456,416,10089],
    "allowedMovementsIds": [10105,10104,10102,11001,10103],
    "allowedCauseClassificationTypesIds": [
        14931,14933,14901,11350,14926,14942,14895,14969,14959,14880,14834,14970,14902,14870,14947,14974,14972,14887,
        14838,14900,14862,14960,14827,14879,14906,14849,14913,14875,14930,14890,14964,14885,14932,14828,14905,14892,
        14858,14939,14845,14830,14888,14925,14898,14873,14924,14975,14839,14907,14971,14911,14886,14936,14893,14961,
        14881,14915,14967,14847,14860,14825,14935,14968,14871,14922,14850,14833,14937,14883,14848,14965,15033,14897,
        14856,14831,14882,14956,14822,14929,14841,14826,15030,14851,14876,14923,14908,14914,14889,14840,14855,14941,
        14874,14891,14921
    ],
    "allowedFollowTypesIds": [3,99,71,54,77,74,20,21,95,101,26,70,2,13],
}

def to_int_if_possible(val):
    try:
        if pd.isna(val):
            return None
        return int(float(val))
    except Exception:
        return None

def build_document(group_df):
    first = group_df.iloc[0]
    susep = str(first["codsusep"]).strip()
    susep_name = first.get("nm_produto", None)
    branch = first.get("nm_ramo", None)
    branch_id = to_int_if_possible(first.get("Ramo", None))

    erp_ids = [to_int_if_possible(x) for x in group_df["cd_produto"].dropna().unique().tolist()]
    erp_ids = [x for x in erp_ids if x is not None]

    def coverage_key(row):
        try:
            grp = int(float(row["cd_grupo_cobertura"]))
        except Exception:
            grp = row["cd_grupo_cobertura"]
        try:
            cov = int(float(row["cd_cobertura"]))
        except Exception:
            cov = row["cd_cobertura"]
        if grp == 0:
            return ("coverage", cov)
        return ("group", grp)

    grouped = {}
    for _, r in group_df.iterrows():
        key = coverage_key(r)
        grouped.setdefault(key, []).append(r)

    coverages = []
    for key, rows in grouped.items():
        r0 = rows[0]
        try:
            grp_val = int(float(r0["cd_grupo_cobertura"]))
        except Exception:
            grp_val = None
        try:
            cov_val = int(float(r0["cd_cobertura"]))
        except Exception:
            cov_val = None

        coverage = {}
        if grp_val not in (None, 0, ""):
            coverage["coverageGroupId"] = int(grp_val)
        else:
            if cov_val not in (None, ""):
                coverage["coverageId"] = int(cov_val)

        coverage["coverageName"] = r0.get("Cobertura", None)
        cause_id = to_int_if_possible(r0.get("cd_causa", None))
        if cause_id is not None:
            coverage["causeTypeId"] = int(cause_id)
        coverage["causeType"] = r0.get("nm_tp_causa", None)

        docs = []
        for rr in rows:
            d = rr.get("Doc", None)
            di = to_int_if_possible(d)
            if di is not None and di not in docs:
                docs.append(di)

        documentation = []
        for d in docs:
            documentation.append({
                "type": "2",
                "documentTypeIds": [],
                "requiresDataValidation": True,
                "isRequired": True,
                "isInsuredDocument": True,
                "isBeneficiaryDocument": False,
                "isActive": True,
                "erpDocumentId": int(d),
                "metadata": ["string"],
                "relatedErpDocumentIds": [0],
                "autoRequiredDocumentIds": [0]
            })
        coverage["documentation"] = documentation
        coverage["active"] = True
        coverages.append(coverage)

    doc = {
        "susepProductNumber": susep,
        "erpProductIds": erp_ids,
        "susepProductName": susep_name,
        "active": STATIC_DOC["active"],
        "allowedStatusesIds": STATIC_DOC["allowedStatusesIds"],
        "allowedMovementsIds": STATIC_DOC["allowedMovementsIds"],
        "allowedCauseClassificationTypesIds": STATIC_DOC["allowedCauseClassificationTypesIds"],
        "allowedFollowTypesIds": STATIC_DOC["allowedFollowTypesIds"],
        "branch": branch,
        "branchId": branch_id,
        "coverages": coverages,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
        "createdUserName": "Johnnata Alves",
        "updatedUserName": "Johnnata Alves"
    }
    return doc

def main():
    df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME, dtype=object)
    df.columns = [c.strip() for c in df.columns]
    if "codsusep" not in df.columns:
        raise KeyError("Coluna 'codsusep' não encontrada no Excel.")

    grouped = df.groupby(df["codsusep"].astype(str).str.strip())
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    coll = db[MONGO_COLLECTION]

    for key, group in grouped:
        document = build_document(group.reset_index(drop=True))
        res = coll.insert_one(document)
        print(f"Inserted {res.inserted_id} for susep {key}")

if __name__ == "__main__":
    main()
