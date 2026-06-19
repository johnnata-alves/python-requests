import os
from dotenv import load_dotenv
import pandas as pd
from pymongo import MongoClient
import re

load_dotenv()

EXCEL_PATH = "dados.xlsx"
SHEET_NAME = "avisados encerrados falta doc"
MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
MONGO_DB = "SinistrosMicroService"
COL_AVISO = "AvisoSinistro"
COL_ANEXO = "AvisoSinistroAnexo"
OUTPUT_PATH = "resultado2.xlsx"

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]
col_aviso = db[COL_AVISO]
col_anexo = db[COL_ANEXO]

df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME, dtype=str)

required_cols = ["nr_bilhete", "cd_sinistro", "ds_status_movimento", "ds_status_processo", "dt_aviso"]
for c in required_cols:
    if c not in df.columns:
        raise SystemExit(f"Coluna ausente no Excel: {c}")

def find_aviso_by_sinistro(cd_sinistro):
    return col_aviso.find_one({"Sinistros": cd_sinistro})

def verifica_existe_saldo(aviso_doc, nr_bilhete):
    if aviso_doc is None:
        return False
    ic = aviso_doc.get("InformacoesComplementares") or {}
    contratoum = ic.get("contratoum")
    try:
        if contratoum is not None and str(contratoum) == str(nr_bilhete):
            return True
    except Exception:
        pass
    icc_list = aviso_doc.get("InformacoesComplementaresContrato") or []
    for item in icc_list:
        contratoum_item = item.get("contratoum")
        if contratoum_item is not None and str(contratoum_item) == str(nr_bilhete):
            return True
    return False

def possui_anexo_certidao_obito(protocolo):
    if protocolo is None:
        return False
    regex = re.compile(r".*_CO_.*", re.IGNORECASE)
    q = {"Protocolo": protocolo, "Key": {"$regex": regex.pattern, "$options": "i"}}
    return col_anexo.find_one({"Protocolo": protocolo, "Key": {"$regex": ".*_CO.*", "$options": "i"}}) is not None

def possui_anexo_contrato(protocolo):
    if protocolo is None:
        return False
    return col_anexo.find_one({"Protocolo": protocolo, "Key": {"$not": re.compile(r".*_CO.*", re.I)}}) is not None

result_rows = []
for idx, row in df.iterrows():
    nr_bilhete = row.get("nr_bilhete")
    cd_sinistro = row.get("cd_sinistro")
    aviso = find_aviso_by_sinistro(cd_sinistro)
    existe_saldo = verifica_existe_saldo(aviso, nr_bilhete)
    protocolo = aviso.get("Protocolo") if aviso else None
    possui_certidao = possui_anexo_certidao_obito(protocolo)
    possui_contrato = possui_anexo_contrato(protocolo)
    out = row.to_dict()
    out["ExisteSaldo"] = existe_saldo
    out["PossuiCertidaoObito"] = possui_certidao
    out["PossuiDocumentoContrato"] = possui_contrato
    result_rows.append(out)

df_out = pd.DataFrame(result_rows)
df_out.to_excel(OUTPUT_PATH, index=False)
print(f"Processo finalizado. Resultado salvo em {OUTPUT_PATH}")
