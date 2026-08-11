"""
Pega registros com Status "Lote Sucesso" em AvisoSinistroAutomacao (HML):
1. Checa no SQL HML se sinistro já existe na mesma apólice -> "Lote Sinistro Ja Criado"
2. Se não existe, busca dados no SQL PRD e cria sinistro via API ERP
3. Sucesso -> "Lote Criado" | Erro -> "Lote Erro Criacao" + message
"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pyodbc
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

HML_MONGO_URI = os.getenv("HML_MONGO_URI")
DB_NAME = "SinistrosMicroService"

SQL_CONNECTION_HML = os.getenv("SQL_CONNECTION_I4PRO_HML")
SQL_CONNECTION_PRD = os.getenv("SQL_CONNECTION_I4PRO_HML")

ERP_BASE = os.getenv("I4PRO_ERP_URL_HML")
if not ERP_BASE:
    print("ERRO: I4PRO_ERP_URL_HML não configurada no .env")
    exit(1)
ERP_URL = f"{ERP_BASE}/run/InserirAvisoSinistro/InserirAvisoSinistro"
ERP_ALTERAR_URL = f"{ERP_BASE}/run/AlterarDetalheSinistro/alterarDetalheSinistro"

WORKERS = 4
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
CD_USUARIO = os.getenv("CD_USUARIO", "usr_claim-engine")
ID_SIN_JUSTIFICATIVA_MOVTO = int(os.getenv("ID_SIN_JUSTIFICATIVA_MOVTO", "25272"))

lock = threading.Lock()
counters = {"sucesso": 0, "erro": 0, "skip": 0, "ja_criado": 0}

# Checa se sinistro já existe em HML na mesma apólice
CHECK_HML_QUERY = """
SELECT TOP 1 csin.nr_sinistro
FROM i4pro_erp..corp_sinistro csin WITH(NOLOCK)
INNER JOIN i4pro_erp..corp_endosso ce WITH(NOLOCK) ON csin.id_endosso = ce.id_endosso
INNER JOIN i4pro_erp..corp_sub_estipulante cse WITH(NOLOCK) ON ce.id_sub = cse.id_sub
INNER JOIN i4pro_erp..corp_apolice ca WITH(NOLOCK) ON cse.id_apolice = ca.id_apolice
WHERE csin.nr_sinistro = ? AND ca.cd_apolice = ?
"""

# Busca dados em PRD para criar sinistro
SQL_PRD_QUERY = """
SELECT DISTINCT
    pess.nr_cnpj_cpf AS cpfSinistrado,
    ca.cd_apolice AS cdApolice,
    rm.nr_ramo AS idRamo,
    csin.nr_item AS idItem,
    mvto.id_produto_cobertura AS idProdutoCobertura,
    csin.id_pessoa_sinistrado AS idSinistrado,
    csin.cd_tp_causa AS cdTpCausa,
    mvto.vl_operacao,
    csin.cd_causa,
    csin.nm_cidade_ocorrencia,
    csin.cd_uf_ocorrencia
FROM
    i4pro_erp..corp_sinistro csin WITH(NOLOCK)
    INNER JOIN i4pro_erp..corp_sin_movto mvto WITH(NOLOCK)
        ON csin.nr_sinistro = mvto.nr_sinistro AND mvto.cd_evento = 10101
    INNER JOIN i4pro_erp..corp_endosso ce WITH(NOLOCK)
        ON csin.id_endosso = ce.id_endosso
    INNER JOIN i4pro_erp..corp_sub_estipulante cse WITH(NOLOCK)
        ON ce.id_sub = cse.id_sub
    INNER JOIN i4pro_erp..corp_apolice ca WITH(NOLOCK)
        ON cse.id_apolice = ca.id_apolice
    INNER JOIN i4pro_erp..corp_ramo rm WITH(NOLOCK)
        ON csin.id_ramo = rm.id_ramo
    INNER JOIN i4pro_erp..corp_pessoas pess WITH(NOLOCK)
        ON pess.id_pessoa = csin.id_pessoa_sinistrado
WHERE
    csin.nr_sinistro = ?
"""


def sinistro_existe_hml(nr_sinistro, apolice):
    conn = pyodbc.connect(SQL_CONNECTION_HML)
    cursor = conn.cursor()
    cursor.execute(CHECK_HML_QUERY, int(nr_sinistro), str(apolice))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row is not None


def buscar_dados_prd(nr_sinistro):
    conn = pyodbc.connect(SQL_CONNECTION_PRD)
    cursor = conn.cursor()
    cursor.execute(SQL_PRD_QUERY, int(nr_sinistro))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return None

    return {
        "cpfSinistrado": row.cpfSinistrado,
        "cdApolice": row.cdApolice,
        "idRamo": row.idRamo,
        "idItem": row.idItem,
        "idProdutoCobertura": row.idProdutoCobertura,
        "idSinistrado": row.idSinistrado,
        "cdTpCausa": row.cdTpCausa,
        "vlEstimado": float(row.vl_operacao) if row.vl_operacao else 0,
        "cdCausa": row.cd_causa,
        "nmCidadeOcorrencia": row.nm_cidade_ocorrencia,
        "cdUfOcorrencia": row.cd_uf_ocorrencia,
    }


def fmt_date(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, str) and value:
        return value
    return None


def build_payload(automacao, aviso, sql_data):
    seg = (aviso or {}).get("Segurado") or {}
    rec = (aviso or {}).get("Reclamante") or {}

    dt_comunicado = fmt_date(automacao.get("DataAviso"))
    dt_ocorrencia_raw = automacao.get("Ocorrencia")
    if isinstance(dt_ocorrencia_raw, datetime):
        dt_ocorrencia = (dt_ocorrencia_raw + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    else:
        dt_ocorrencia = fmt_date(dt_ocorrencia_raw)

    cpf_sinistrado = automacao.get("CPF") or seg.get("CpfCnpj") or sql_data.get("cpfSinistrado")

    payload = {
        "cdApolice": int(automacao.get("Apolice") or sql_data["cdApolice"]),
        "nrEndosso": 0,
        "idRamo": sql_data["idRamo"],
        "vlEstimado": sql_data["vlEstimado"],
        "dtComunicado": dt_comunicado,
        "dtOcorrencia": dt_ocorrencia,
        "idItem": sql_data["idItem"],
        "idProdutoCobertura": sql_data["idProdutoCobertura"],
        "idSinistrado": sql_data["idSinistrado"],
        "idSinJustificativaMovto": ID_SIN_JUSTIFICATIVA_MOVTO,
        "cdMoeda": 1,
        "hrOcorrencia": "00:00",
        "nmReclamante": "Banco PAN S.A.",
        "nrCnpjCpfReclamante": "59285411000113",
        "idSinRelacao": rec.get("Relacao"),
        "nrCnpjCpfSinistrado": cpf_sinistrado,
        "dvSinistradoSegurado": True,
        "cdTpCausa": sql_data.get("cdTpCausa"),
        "nmDescricaoSinistro": "Abertura de Sinistro",
        "cdUsuario": CD_USUARIO,
        "dvLiberaConsistencia": True,
        "dvJuridico": False,
        "dvAjusteResseguro": True,
    }

    return payload


def enviar_erp(payload):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    client_id = os.getenv("I4PRO_CLIENT_ID")
    client_secret = os.getenv("I4PRO_CLIENT_SECRET")
    if client_id:
        headers["clientId"] = client_id
    if client_secret:
        headers["clientSecret"] = client_secret

    resp = requests.post(ERP_URL, headers=headers, data=json.dumps(payload, default=str))
    resp.raise_for_status()
    return resp.json()


def alterar_sinistro(nr_sinistro, sql_data):
    """Altera detalhe do sinistro criado com dados do SQL PRD."""
    headers = {"Content-Type": "application/json; charset=utf-8"}
    client_id = os.getenv("I4PRO_CLIENT_ID")
    client_secret = os.getenv("I4PRO_CLIENT_SECRET")
    if client_id:
        headers["clientId"] = client_id
    if client_secret:
        headers["clientSecret"] = client_secret

    dados_alterar = {
        "nrSinistro": int(nr_sinistro),
        "cdStatus": 801,
        "cdTpCausa": sql_data.get("cdTpCausa"),
        "cdCausa": sql_data.get("cdCausa"),
        "cdUfOcorrencia": sql_data.get("cdUfOcorrencia"),
        "nmCidadeOcorrencia": sql_data.get("nmCidadeOcorrencia") or "",
        "cdUsuario": CD_USUARIO,
    }

    resp = requests.post(ERP_ALTERAR_URL, headers=headers, data=json.dumps(dados_alterar, default=str))
    resp.raise_for_status()
    return resp.json()


def processar_item(item):
    hml_client = MongoClient(HML_MONGO_URI)
    hml_db = hml_client[DB_NAME]
    col_automacao = hml_db["AvisoSinistroAutomacao"]

    item_id = item["_id"]
    sinistro = item.get("Sinistro", "")
    protocolo = item.get("Protocolo", "")
    cpf = item.get("CPF", "")
    apolice = item.get("Apolice", "")

    try:
        if not sinistro:
            raise ValueError("Campo Sinistro vazio")

        # # 1. Checar se já existe em HML (mesmo sinistro + apólice)
        # if sinistro and apolice and sinistro_existe_hml(sinistro, apolice):
        #     col_automacao.update_one(
        #         {"_id": item_id},
        #         {"$set": {
        #             "Status": "Lote Sinistro Ja Criado",
        #             "message": f"Sinistro {sinistro} já existe em HML na apólice {apolice}",
        #             "ProcessamentoSinistro": datetime.utcnow()
        #         }}
        #     )
        #     with lock:
        #         counters["ja_criado"] += 1
        #     return

        # 2. Buscar dados no SQL PRD
        sql_data = buscar_dados_prd(sinistro)
        if not sql_data:
            raise ValueError(f"Sinistro {sinistro} não encontrado no SQL PRD")

        # 3. Buscar AvisoSinistro em HML
        aviso = None
        if protocolo:
            aviso = hml_db["AvisoSinistro"].find_one({"Protocolo": protocolo})

        # 4. Montar payload
        payload = build_payload(item, aviso, sql_data)

        if DRY_RUN:
            col_automacao.update_one(
                {"_id": item_id},
                {"$set": {
                    "Status": "Lote DryRun",
                    "payload": payload,
                    "ProcessamentoSinistro": datetime.utcnow()
                }}
            )
            with lock:
                counters["skip"] += 1
            return

        # 5. Criar sinistro via ERP
        resultado = enviar_erp(payload)
        cd_retorno = resultado.get("cd_retorno")

        if cd_retorno == 0:
            nr_sinistro_criado = resultado.get("nrSinistro")

            # Alterar detalhe do sinistro com dados do SQL PRD
            try:
                alterar_sinistro(nr_sinistro_criado, sql_data)
            except Exception as e_alt:
                # Sinistro criado mas falhou ao alterar
                col_automacao.update_one(
                    {"_id": item_id},
                    {"$set": {
                        "Status": "Lote Criado",
                        "Sinistro": str(nr_sinistro_criado),
                        # "SinistroAntigo": sinistro,
                        "message": f"Sinistro {nr_sinistro_criado} criado. AVISO: falha ao alterar: {e_alt}",
                        "ProcessamentoSinistro": datetime.utcnow()
                    }}
                )
                with lock:
                    counters["sucesso"] += 1
                return

            col_automacao.update_one(
                {"_id": item_id},
                {"$set": {
                    "Status": "Lote Criado",
                    "Sinistro": str(nr_sinistro_criado),
                    # "SinistroAntigo": sinistro,
                    "message": f"Sinistro {nr_sinistro_criado} criado e alterado com sucesso",
                    "ProcessamentoSinistro": datetime.utcnow()
                }}
            )
            with lock:
                counters["sucesso"] += 1
        else:
            msg = resultado.get("nm_retorno", "Erro desconhecido")
            col_automacao.update_one(
                {"_id": item_id},
                {"$set": {
                    "Status": "Lote Erro Criacao",
                    "message": f"ERP retornou cd_retorno={cd_retorno}: {msg}",
                    "ProcessamentoSinistro": datetime.utcnow()
                }}
            )
            with lock:
                counters["erro"] += 1

    except Exception as e:
        col_automacao.update_one(
            {"_id": item_id},
            {"$set": {
                "Status": "Lote Erro Criacao",
                "message": str(e),
                "ProcessamentoSinistro": datetime.utcnow()
            }}
        )
        with lock:
            counters["erro"] += 1

    finally:
        hml_client.close()


def main():
    if not SQL_CONNECTION_PRD:
        print("ERRO: SQL_CONNECTION_I4PRO_PRD_V2 não configurada no .env")
        return
    if not SQL_CONNECTION_HML:
        print("ERRO: SQL_CONNECTION_I4PRO_HML não configurada no .env")
        return

    hml_client = MongoClient(HML_MONGO_URI)
    hml_db = hml_client[DB_NAME]

    lotes = list(hml_db["AvisoSinistroAutomacao"].find({"Status": "Lote Sucesso"}))
    hml_client.close()

    total = len(lotes)
    print(f"Registros com Status 'Lote Sucesso': {total}")
    print(f"Workers: {WORKERS} | DRY_RUN: {DRY_RUN}\n")

    if not lotes:
        print("Nada para processar.")
        return

    with tqdm(total=total, desc="Criando sinistros", unit="doc") as pbar:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(processar_item, item): item for item in lotes}
            for future in as_completed(futures):
                future.result()
                pbar.update(1)

    print(f"\nFinalizado!")
    print(f"  Total:        {total}")
    print(f"  Criado:       {counters['sucesso']}")
    print(f"  Ja criado:    {counters['ja_criado']}")
    print(f"  Erro:         {counters['erro']}")
    print(f"  DryRun:       {counters['skip']}")


if __name__ == "__main__":
    main()
