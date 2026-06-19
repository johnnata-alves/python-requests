import os
from dotenv import load_dotenv
import pyodbc
import pandas as pd
from pymongo import MongoClient
from datetime import datetime

load_dotenv()

conn_str = os.getenv("SQL_CONNECTION_I4PRO_PRD")
sql_conn = pyodbc.connect(conn_str)

sql_query = """
SELECT DISTINCT csin.nr_sinistro, ca.cd_produto, csin.dt_ocorrencia, csin.dt_comunicado, cppp.nm_produto,
                cs.nm_status, ca.cd_apolice,
                REPLICATE('0', 11 - LEN(CONVERT(varchar,cp.nr_cnpj_cpf))) + CONVERT(varchar,cp.nr_cnpj_cpf) AS cpf,
                cp.nm_pessoa, civ.nr_chave_externa
FROM i4pro_erp..corp_sinistro csin (NOLOCK)
INNER JOIN i4pro_erp..corp_status cs (NOLOCK) ON csin.cd_status = cs.cd_status
INNER JOIN i4pro_erp..corp_endosso ce (NOLOCK) ON csin.id_endosso = ce.id_endosso
INNER JOIN i4pro_erp..corp_sub_estipulante cse (NOLOCK) ON cse.id_sub = ce.id_sub
INNER JOIN i4pro_erp..corp_apolice ca (NOLOCK) ON ca.id_apolice = cse.id_apolice
INNER JOIN i4pro_erp..corp_pessoas cp (NOLOCK) ON csin.id_pessoa_sinistrado = cp.id_pessoa
LEFT JOIN i4pro_erp..corp_apolice ca_pai WITH(NOLOCK) ON ca_pai.id_apolice = ca.id_apolice_pai
INNER JOIN i4pro_erp..corp_produto cppp WITH(NOLOCK) ON ca.cd_produto = cppp.cd_produto
INNER JOIN i4pro_erp..corp_endosso_item_vida ceiv WITH(NOLOCK) ON csin.id_endosso = ceiv.id_endosso
INNER JOIN i4pro_erp..corp_item_vida civ WITH(NOLOCK) ON ceiv.id_pessoa_item = civ.id_pessoa_item
WHERE ca.cd_produto IN (272, 252) AND csin.dt_comunicado > '2023-01-01'
AND csin.cd_status IN (477, 426, 454, 801, 455, 10081, 453, 456, 10089, 450, 10082, 848, 421, 470, 10090)
ORDER BY 4 DESC
"""

df_sql = pd.read_sql(sql_query, sql_conn)

mongo_client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
db = mongo_client["SinistrosMicroService"]
dbOCR = mongo_client["OCR"]

def get_mongo_data(cpf, dt_ocorrencia):
    avisos = list(db["AvisoSinistro"].find({
        "$and": [
            {"Segurado.CpfCnpj": cpf},
            {"Ocorrencia": {"$gt": datetime.combine(dt_ocorrencia, datetime.min.time())}},
            {"Ocorrencia": {"$lt": datetime.combine(dt_ocorrencia, datetime.max.time())}},
            {"InformacoesComplementares.origemdocumento": "Aviso API V4"},
            {"CnpjEstipulante": "59285411000113"}
        ]
    }))

    if not avisos:
        return None, None, "Nenhum anexo recebido"

    protocolos = [aviso["Protocolo"] for aviso in avisos]
    anexos = list(db["AvisoSinistroAnexo"].find({"Protocolo": {"$in": protocolos}}))

    if not anexos:
        return protocolos, None, "Nenhum anexo recebido"

    ult_anexo = max(anexos, key=lambda x: x["DataInclusaoAnexo"])["DataInclusaoAnexo"]
    status = ""

    tem_certidao_obito = any("_CO_" in a["Key"] for a in anexos)

    if tem_certidao_obito:
        for a in anexos:
            nome_arquivo = a["Key"].replace("TemporaryFiles/", "")
            ocr_log = dbOCR["AtomicLog"].find_one({"NomeArquivo": nome_arquivo})

            if ocr_log:
                if "Resposta" in ocr_log and "Arquivos" in ocr_log["Resposta"]:
                    arquivos = ocr_log["Resposta"]["Arquivos"]
                    if arquivos and "TipoArquivo" in arquivos[0]:
                        tipos_documento = [t["NomeTipoArquivo"] for t in arquivos[0]["TipoArquivo"] if "NomeTipoArquivo" in t]
                    else:
                        tipos_documento = []
                else:
                    tipos_documento = []
                if any(t in ["21 - CNH", "21 - RG", "21 - CPF"] for t in tipos_documento):
                    status = "Docs Ok"
                    break
                else:
                    status = "Documento de identificação não recebido"
    else:
        status = "Sem certidão de óbito"

    return protocolos, ult_anexo, status

filtered_rows = []
total_rows = len(df_sql)
for index, row in df_sql.iterrows():
    protocolos, ult_anexo, status = get_mongo_data(row["cpf"], row["dt_ocorrencia"])
    if protocolos:
        row["Protocolos"] = ", ".join(protocolos)
        row["DataUltimoAnexo"] = ult_anexo
        row["Status"] = status
        filtered_rows.append(row)

    print(f"Processados: {index + 1}/{total_rows} registros")

df_filtered = pd.DataFrame(filtered_rows)
df_filtered["nr_sinistro"] = df_filtered["nr_sinistro"].astype(str)
df_filtered["cd_apolice"] = df_filtered["cd_apolice"].astype(str)
df_filtered["dt_ocorrencia"] = pd.to_datetime(df_filtered["dt_ocorrencia"]).dt.strftime("%d/%m/%Y")
df_filtered["dt_comunicado"] = pd.to_datetime(df_filtered["dt_comunicado"]).dt.strftime("%d/%m/%Y")
df_filtered["DataUltimoAnexo"] = pd.to_datetime(df_filtered["DataUltimoAnexo"]).dt.strftime("%d/%m/%Y")
df_filtered.to_excel("Relatorio_Sinistros.xlsx", index=False)

print("Relatório gerado com sucesso!")
