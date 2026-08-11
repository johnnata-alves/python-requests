import json
import os
from datetime import datetime

import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

ERP_BASE = os.getenv("I4PRO_ERP_URL", "http://i4pro/i4protoo_prd/erpws")
CONSULTA_URL = f"{ERP_BASE}/run/Sinistro/ConsultaDetalheSinistro"
REG_DOCS_URL = f"{ERP_BASE}/run/Sinistro/RegDocumentos"
ALTERAR_URL = f"{ERP_BASE}/run/AlterarDetalheSinistro/alterarDetalheSinistro"

DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
CD_USUARIO = os.getenv("CD_USUARIO", "usr_claim-engine")

# documentos que devem PERMANECER solicitados; o resto e removido
MANTER_DOCUMENTOS = {124, 326, 314, 57}

# lista corrida de sinistros a processar
SINISTROS = [
1008200018645,
1008200018646,
1008200018647,
1008200018648,
1008200018649,
1008200018650,
2007700050220,
2007700050221,
2007700050222,
2007700050223,
2007700050224,
2007700050225,
1008200018653,
1008200018654,
1008200018655,
1008200018656,
1008200018657,
1008200018658,
1008200018659,
1008200018660,
1008200018661,
1008200018662,
1008200018663,
1008200018664,
1008200018665,
1008200018666,
1008200018667,
1008200018668,
1008200018669,
1008200018670,
2007700050160,
2007700050159,
2007700050161,
2007700050162,
2007700050197,
2007700050163,
2007700050164,
2007700050198,
2007700050165,
2007700050199,
2007700050166,
2007700050200,
2007700050167,
2007700050168,
2007700050169,
2007700050170,
2007700050171,
2007700050172,
2007700050201,
2007700050202,
2007700050203,
2007700050204,
2007700050173,
2007700050174,
2007700050205,
2007700050175,
2007700050176,
2007700050206,
2007700050177,
2007700050207,
2007700050178,
2007700050208,
2007700050209,
2007700031755,
2007700050210,
2007700050211,
2007700050179,
2007700050212,
2007700050213,
2007700050180,
2007700050180,
2007700050181,
2007700050182,
2007700050214,
2007700050183,
2007700050184,
2007700050185,
2007700050186,
2007700050215,
2007700050187,
2007700050188,
2007700050189,
2007700050190,
2007700050191,
2007700050192,
2007700050193,
2007700050194,
2007700050216,
2007700050217,
2007700050218,
2007700050195,
2007700050196,
2007700050219,

]


def headers():
    h = {"Content-Type": "application/json; charset=utf-8"}
    client_id = os.getenv("I4PRO_CLIENT_ID")
    client_secret = os.getenv("I4PRO_CLIENT_SECRET")
    if client_id:
        h["clientId"] = client_id
    if client_secret:
        h["clientSecret"] = client_secret
    return h


def to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def alterar_detalhe(nr_sinistro):
    dados = {
        "nrSinistro": nr_sinistro,
        "cdStatus": 801,
        "cdTpCausa": 2,
        "cdCausa": 15033,
        "cdUfOcorrencia": 1,
        "nmCidadeOcorrencia": "São Paulo",
        "cdUsuario": "usr_sinistro_motor",
    }
    resp = requests.post(ALTERAR_URL, headers=headers(), data=json.dumps(dados))
    return resp.status_code == 200


def consultar_detalhe(nr_sinistro):
    resp = requests.post(
        CONSULTA_URL, headers=headers(), data=json.dumps({"numSinistro": nr_sinistro})
    )
    resp.raise_for_status()
    return resp.json()


def remover_documentos(nr_sinistro, documentos_detalhe):
    data_atual = datetime.now().strftime("%Y-%m-%d")
    documentos = []

    # pega idProdutoCobertura do primeiro doc ativo como fallback
    id_produto_cob = None
    for doc in documentos_detalhe:
        if str(doc.get("dvDocumentoExcluido")) == "0" and doc.get("idProdutoCobertura"):
            id_produto_cob = doc["idProdutoCobertura"]
            break

    # ids presentes no sinistro (somente nao excluidos)
    ids_existentes = set()
    docs_ativos = [d for d in documentos_detalhe if str(d.get("dvDocumentoExcluido")) == "0"]

    for doc in docs_ativos:
        id_doc = to_int(doc.get("idDocumento"))
        if id_doc is not None:
            ids_existentes.add(id_doc)

    # remover docs que nao estao em MANTER_DOCUMENTOS
    for doc in docs_ativos:
        id_doc = to_int(doc.get("idDocumento"))
        if id_doc is None or id_doc in MANTER_DOCUMENTOS:
            continue
        documentos.append({
            "dvSolicitar": False,
            "dtSolicitacao": data_atual,
            "dtRecebimento": data_atual,
            "cdOperacao": 1,
            "cdUsuario": CD_USUARIO,
            "idDocumento": str(id_doc),
            "idSinDocumentoClassificacao": "1",
            "nmJustificativa": "documento não requerido",
            "idProdutoCobertura": doc.get("idProdutoCobertura"),
        })

    # adicionar docs de MANTER_DOCUMENTOS que nao existem no sinistro
    for id_doc in MANTER_DOCUMENTOS:
        if id_doc not in ids_existentes:
            documentos.append({
                "dvSolicitar": True,
                "dtSolicitacao": data_atual,
                "dtRecebimento": None,
                "cdOperacao": 2,
                "cdUsuario": "usr_motor_regulacao",
                "idDocumento": str(id_doc),
                "idSinDocumentoClassificacao": "1",
                "nmJustificativa": "documento requerido para análise",
                "idProdutoCobertura": id_produto_cob,
            })

    if not documentos:
        return True, "Nenhum documento para remover"

    if DRY_RUN:
        return True, f"DRY_RUN: removeria {len(documentos)} doc(s)"

    resp = requests.post(
        REG_DOCS_URL,
        headers=headers(),
        data=json.dumps({"nrSinistro": nr_sinistro, "Documentos": documentos}),
    )
    resp.raise_for_status()
    resultado = resp.json()

    if "Documentos" not in resultado:
        return False, "Retorno sem 'Documentos'"

    for doc in resultado["Documentos"]:
        if doc.get("cdRetorno") != 0:
            return False, f"Falha no doc {doc.get('idDocumento')}: {doc.get('nmRetorno')}"

    return True, f"Removidos {len(documentos)} doc(s)"


def processar(nr_sinistro):
    try:
        detalhe = consultar_detalhe(nr_sinistro)
    except Exception as exc:
        return f"ERRO CONSULTA: {exc}"

    if detalhe.get("cd_retorno") != 0:
        return f"ERRO CONSULTA ERP: {detalhe.get('nm_retorno')}"

    if not DRY_RUN:
        try:
            if not alterar_detalhe(nr_sinistro):
                return "ERRO: falha ao alterar detalhe do sinistro"
        except Exception as exc:
            return f"ERRO ALTERAR: {exc}"

    documentos_detalhe = detalhe.get("documentos") or []
    try:
        ok, msg = remover_documentos(nr_sinistro, documentos_detalhe)
        return ("OK: " if ok else "ERRO: ") + msg
    except Exception as exc:
        return f"ERRO REMOCAO: {exc}"


def main():
    print(f"ERP: {REG_DOCS_URL} | DRY_RUN={DRY_RUN} | sinistros={len(SINISTROS)}")

    for sinistro in tqdm(SINISTROS, desc="Removendo docs"):
        nr = to_int(sinistro)
        if not nr:
            print(f"{sinistro} -> ERRO: valor invalido")
            continue
        resultado = processar(nr)
        print(f"{nr} -> {resultado}")


if __name__ == "__main__":
    main()
