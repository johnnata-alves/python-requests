import json
import os
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DB_NAME = "SinistrosMicroService"
COLLECTION = "AvisoSinistro"

INDEXED_URI = os.getenv("INDEXED_ENDORSEMENT_URI", MONGO_URI)
INDEXED_DB = "indexed_endorsement"
INDEXED_COL = "person_items"

STAKEHOLDERS_URI = os.getenv("INDEXED_STAKEHOLDERS_URI", INDEXED_URI)
STAKEHOLDERS_DB = "indexed_stakeholders"
STAKEHOLDERS_COL = "identification"

ID_SIN_JUSTIFICATIVA_MOVTO = int(os.getenv("ID_SIN_JUSTIFICATIVA_MOVTO", "25272"))

ERP_BASE = os.getenv("I4PRO_ERP_URL", "http://i4pro/i4protoo_prd/erpws")
ERP_URL = f"{ERP_BASE}/run/InserirAvisoSinistro/InserirAvisoSinistro"

EXCEL_PATH = os.getenv("EXCEL_PATH", "integracao/avisos.xlsx")
STATUS_COL = "status_processamento"
SINISTRO_COL = "nrSinistro"

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# defaults para campos obrigatorios que NAO existem no AvisoSinistro
CD_USUARIO = os.getenv("CD_USUARIO", "usr_claim-engine")
CD_MOEDA = int(os.getenv("CD_MOEDA", "1"))


def fmt_date(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, str) and value:
        return value
    return None


def to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_float(value):
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def coverage_morte(endorsement):
    for cov in endorsement.get("coverages") or []:
        if "MORTE" in (cov.get("description") or "").upper():
            return cov
    return None


def find_apolice(doc, apolice_planilha):
    """Localiza o Produto/Apolice do doc que casa com a apolice da planilha."""
    alvo = to_int(apolice_planilha)
    for produto in doc.get("Produtos") or []:
        for apo in produto.get("Apolices") or []:
            if to_int(apo.get("NumeroApolice")) == alvo:
                return produto, apo
    return None, None


def build_payload(doc, endorsement, stakeholder, apolice_planilha, cpf_planilha):
    """Retorna (payload, faltantes) com o de/para possivel."""
    faltantes = []

    seg = doc.get("Segurado") or {}
    rec = doc.get("Reclamante") or {}
    sin = doc.get("Sinistrado") or {}
    info = doc.get("InformacoesComplementares") or {}

    produto, apo = find_apolice(doc, apolice_planilha)
    cobertura = ((apo or {}).get("Coberturas") or [{}])[0] if apo else {}


    # dados vindos do indexed_endorsement.person_items
    endorsement = endorsement or {}
    cov_morte = coverage_morte(endorsement)

    id_item = endorsement.get("life_endorsement_item_id")
    id_produto_cobertura = (cov_morte or {}).get("product_coverage_id")
    vl_estimado = to_float(((cov_morte or {}).get("is") or {}).get("amount"))

    if id_item is None:
        faltantes.append("idItem")
    if id_produto_cobertura is None:
        faltantes.append("idProdutoCobertura")
    if vl_estimado is None:
        faltantes.append("vlEstimado")
    dt_comunicado = fmt_date(info.get("datacomusinistro") or doc.get("DataDoAviso"))
    if dt_comunicado is None:
        faltantes.append("dtComunicado")

    dt_ocorrencia = fmt_date(doc.get("Ocorrencia"))
    if dt_ocorrencia is None:
        faltantes.append("dtOcorrencia")

    cpf_sinistrado = sin.get("CpfCnpj") or seg.get("CpfCnpj") or str(cpf_planilha)

    # dados do sinistrado vindos do indexed_stakeholders.identification
    stakeholder = stakeholder or {}
    id_sinistrado = stakeholder.get("personIdErp")
    if id_sinistrado is None:
        faltantes.append("idSinistrado")

    payload = {
        # obrigatorios
        "cdApolice": to_int(apolice_planilha),
        "nrEndosso": 0,
        "idRamo": 39,
        "vlEstimado": vl_estimado,
        "dtComunicado": dt_comunicado,
        "dtOcorrencia": dt_ocorrencia,
        "idItem": id_item,
        "idProdutoCobertura": id_produto_cobertura,
        "idSinistrado": id_sinistrado,
        "idSinJustificativaMovto": ID_SIN_JUSTIFICATIVA_MOVTO,
        # opcionais mapeaveis
        "cdMoeda": CD_MOEDA,
        "hrOcorrencia": "00:00",
        "nmReclamante": rec.get("Nome"),
        "nrCnpjCpfReclamante": rec.get("CpfCnpj"),
        "idSinRelacao": rec.get("Relacao"),
        "nmSinistrado": sin.get("Nome") or seg.get("Nome"),
        "nrCnpjCpfSinistrado": cpf_sinistrado,
        "dvSinistradoSegurado": bool(
            sin.get("CpfCnpj") and sin.get("CpfCnpj") == seg.get("CpfCnpj")
        ),
        "cdTpCausa": cobertura.get("TipoCausaId"),
        "nmDescricaoSinistro": (doc.get("Relato") or "")[:16] or None,
        "cdUsuario": CD_USUARIO,
        "dvLiberaConsistencia": True,
        "dvJuridico": False,
        "dvAjusteResseguro": True,
    }

    return payload, faltantes


def enviar(payload):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    client_id = os.getenv("I4PRO_CLIENT_ID")
    client_secret = os.getenv("I4PRO_CLIENT_SECRET")
    if client_id:
        headers["clientId"] = client_id
    if client_secret:
        headers["clientSecret"] = client_secret

    resp = requests.post(ERP_URL, headers=headers, data=json.dumps(payload))
    resp.raise_for_status()
    return resp.json()


def main():
    client = MongoClient(MONGO_URI)
    col = client[DB_NAME][COLLECTION]

    indexed_client = MongoClient(INDEXED_URI)
    col_endorsement = indexed_client[INDEXED_DB][INDEXED_COL]

    stakeholders_client = MongoClient(STAKEHOLDERS_URI)
    col_stakeholder = stakeholders_client[STAKEHOLDERS_DB][STAKEHOLDERS_COL]

    df = pd.read_excel(EXCEL_PATH, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    for req in ("CPF", "Apolice"):
        if req not in df.columns:
            raise ValueError(f"Coluna obrigatoria ausente na planilha: {req}")

    if STATUS_COL not in df.columns:
        df[STATUS_COL] = ""
    if SINISTRO_COL not in df.columns:
        df[SINISTRO_COL] = ""
    for col_extra in ("Protocolo", "Ocorrencia", "term_start_date", "term_end_date"):
        if col_extra not in df.columns:
            df[col_extra] = ""

    print(f"ERP: {ERP_URL} | DRY_RUN={DRY_RUN} | linhas={len(df)}")

    def salvar():
        df.to_excel(EXCEL_PATH, index=False, engine="openpyxl")

    def processar_linha(idx, row):
        status_atual = str(row.get(STATUS_COL) or "").strip()
        if status_atual.startswith("OK: sinistro"):
            return False  # ja processado, nao precisa salvar

        apolice = str(row.get("Apolice") or "").strip()
        cpf = str(row.get("CPF") or "").strip()
        cpf_identificacao = cpf.zfill(11)

        if not cpf:
            df.at[idx, STATUS_COL] = "ERRO: CPF vazio"
            return True

        doc = col.find_one({"Segurado.CpfCnpj": cpf_identificacao})
        if not doc:
            df.at[idx, STATUS_COL] = "ERRO: aviso nao encontrado"
            return True

        # enriquecer planilha com dados do AvisoSinistro
        df.at[idx, "Protocolo"] = doc.get("Protocolo") or ""
        ocorrencia = doc.get("Ocorrencia")
        df.at[idx, "Ocorrencia"] = ocorrencia.strftime("%Y-%m-%d") if ocorrencia else ""

        endorsement = col_endorsement.find_one(
            {
                "policy_number": apolice,
                "coverages.description": {"$regex": "MORTE", "$options": "i"},
            },
            sort=[("endorsement_id", 1)],
        )
        if not endorsement:
            df.at[idx, STATUS_COL] = "ERRO: endosso com cobertura MORTE nao encontrado (person_items)"
            return True

        # enriquecer planilha com dados do person_items
        items = endorsement.get("items") or []
        if items:
            df.at[idx, "term_start_date"] = items[0].get("term_start_date") or ""
            df.at[idx, "term_end_date"] = items[0].get("term_end_date") or ""

        stakeholder = col_stakeholder.find_one({"document": cpf_identificacao})
        if not stakeholder:
            df.at[idx, STATUS_COL] = "ERRO: sinistrado nao encontrado (identification)"
            return True

        payload, faltantes = build_payload(doc, endorsement, stakeholder, apolice, cpf)

        if faltantes:
            df.at[idx, STATUS_COL] = "SEM DE/PARA: " + ", ".join(sorted(set(faltantes)))
            return True

        if DRY_RUN:
            df.at[idx, STATUS_COL] = "DRY_RUN OK"
            return True

        try:
            resultado = enviar(payload)
            cd_retorno = resultado.get("cd_retorno")
            if cd_retorno == 0:
                nr_sinistro = resultado.get("nrSinistro")
                df.at[idx, SINISTRO_COL] = str(nr_sinistro or "")
                df.at[idx, STATUS_COL] = f"OK: sinistro {nr_sinistro}"
            else:
                df.at[idx, STATUS_COL] = f"ERRO ERP: {resultado.get('nm_retorno')}"
        except Exception as exc:
            df.at[idx, STATUS_COL] = f"ERRO ENVIO: {exc}"
        return True

    for idx, row in tqdm(df.iterrows(), total=len(df), desc="Processando"):
        alterou = processar_linha(idx, row)
        if alterou:
            salvar()  # persiste a cada linha para nao perder progresso

    print(f"Planilha atualizada: {EXCEL_PATH}")


if __name__ == "__main__":
    main()
