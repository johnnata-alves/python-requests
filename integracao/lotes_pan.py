import os
from dotenv import load_dotenv
import pyodbc
import pymongo
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

conn_str = os.getenv("SQL_CONNECTION_I4PRO_PRD")
sql_conn = pyodbc.connect(conn_str)
sql_cursor = sql_conn.cursor()

sql_query = """
SELECT DISTINCT
    REPLICATE('0', 11 - LEN(CONVERT(varchar, cp.nr_cnpj_cpf))) + CONVERT(varchar, cp.nr_cnpj_cpf) AS cpf,
    ca.cd_produto,
    cppp.nm_produto,
    csin.nr_sinistro,
    ca.cd_apolice,
    csin.id_endosso,
    CONVERT(varchar(max), csin.dt_sistema, 103) AS data_sistema,
    csin.id_pessoa_sinistrado
FROM i4pro_erp..corp_sinistro csin
    INNER JOIN i4pro_erp..corp_status cs (NOLOCK) ON csin.cd_status = cs.cd_status
    INNER JOIN i4pro_erp..corp_endosso ce (NOLOCK) ON csin.id_endosso = ce.id_endosso
    INNER JOIN i4pro_erp..corp_sub_estipulante cse (NOLOCK) ON cse.id_sub = ce.id_sub
    INNER JOIN i4pro_erp..corp_apolice ca (NOLOCK) ON ca.id_apolice = cse.id_apolice
    INNER JOIN i4pro_erp..corp_pessoas cp ON csin.id_pessoa_sinistrado = cp.id_pessoa
    INNER JOIN i4pro_erp..corp_produto cppp ON ca.cd_produto = cppp.cd_produto
WHERE
    csin.cd_status = 801
    AND ca.cd_produto IN (251, 272, 363)
ORDER BY csin.nr_sinistro DESC
"""
sql_cursor.execute(sql_query)
sinistros_geral = sql_cursor.fetchall()

sinistros_lista = [str(s[3]) for s in sinistros_geral]

mongo_client = pymongo.MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
db = mongo_client["SinistrosMicroService"]
dbOCR = mongo_client["OCR"]

def fetch_anexos():
    anexos_resultados = db.AvisoSinistroAnexo.find({"Protocolo": {"$in": protocolos_lista}})
    anexos_dict = {}
    for anexo in anexos_resultados:
        protocolo = anexo.get("Protocolo")
        if protocolo:
            if isinstance(protocolo, list):
                for p in protocolo:
                    anexos_dict[p] = anexo
            else:
                anexos_dict[protocolo] = anexo
    return anexos_dict

def fetch_ocr():
    ocr_resultados = dbOCR.AtomicLog_Obito.find({"Protocolo": {"$in": protocolos_lista}})
    ocr_dict = {}
    for ocr in ocr_resultados:
        protocolo = ocr.get("Protocolo")
        if protocolo:
            if isinstance(protocolo, list):
                for p in protocolo:
                    ocr_dict.setdefault(p, []).append(ocr)
            else:
                ocr_dict.setdefault(protocolo, []).append(ocr)
    return ocr_dict

def fetch_timeline():
    timeline_resultados = db.SinistroTimeline.find({"Protocolo": {"$in": protocolos_lista}})
    timeline_dict = {}
    for timeline in timeline_resultados:
        protocolo = timeline.get("Protocolo")
        if protocolo:
            if isinstance(protocolo, list):
                for p in protocolo:
                    timeline_dict.setdefault(p, []).append(timeline)
            else:
                timeline_dict.setdefault(protocolo, []).append(timeline)
    return timeline_dict

avisos_sinistros = db.AvisoSinistro.find({"Sinistros": {"$in": sinistros_lista}})
avisos_dict = {}
protocolos_lista = []

for aviso in avisos_sinistros:
    sinistros = aviso.get("Sinistros", [])
    if isinstance(sinistros, list):
        for sinistro in sinistros:
            avisos_dict[sinistro] = aviso
    else:
        avisos_dict[sinistros] = aviso

    protocolo = aviso.get("Protocolo")
    if protocolo:
        if isinstance(protocolo, list):
            protocolos_lista.extend(protocolo)
        else:
            protocolos_lista.append(protocolo)

with ThreadPoolExecutor() as executor:
    future_anexos = executor.submit(fetch_anexos)
    future_ocr = executor.submit(fetch_ocr)
    future_timeline = executor.submit(fetch_timeline)

anexos_dict = future_anexos.result()
ocr_dict = future_ocr.result()
timeline_dict = future_timeline.result()

resultados = []

for sinistro in sinistros_geral:
    nr_sinistro = sinistro[3]
    cpf = sinistro[0]
    cd_produto = sinistro[1]
    nm_produto = sinistro[2]
    cd_apolice = sinistro[4]
    id_endosso = sinistro[5]
    data_sistema = sinistro[6]
    id_pessoa_sinistrado = sinistro[7]

    protocolo = avisos_dict.get(str(nr_sinistro))

    if protocolo:
        ocorrencia = protocolo.get("Ocorrencia", "")
        protocolo_id = protocolo.get("Protocolo", "")
        informacoes_complementares = protocolo.get("InformacoesComplementares", {})
        origem_documento = informacoes_complementares.get("origemdocumento", "")
        saldo_devedor_um = informacoes_complementares.get("saldodevedorum", "")
        contrato_um = informacoes_complementares.get("contratoum", "")

        if origem_documento != "Aviso API V4":
            classificacao = "Fora canal parceiro"
        else:
            anexo = anexos_dict.get(protocolo_id)
            if not anexo:
                classificacao = "Documentação não recebida"
            else:
                ocr_lista = ocr_dict.get(protocolo_id, [])
                documento_identificacao_ok = any(ocr.get("DocumentoIdentificacao", False) for ocr in ocr_lista)
                certidao_obito_ok = any("Certidão de Óbito" in ocr.get("TiposArquivo", []) for ocr in ocr_lista)

                if not documento_identificacao_ok:
                    classificacao = "Documento de identificação não encontrado"
                elif not certidao_obito_ok:
                    classificacao = "Certidão de óbito não identificada"
                else:
                    timeline_lista = timeline_dict.get(protocolo_id, [])
                    evento_suicidio = any(
                        t.get("Codigo") == "30021" and "Possível suicídio" in t.get("Descricao", "")
                        for t in timeline_lista
                    )

                    if evento_suicidio:
                        classificacao = "Possível suicídio identificado"
                    else:
                        classificacao = "Docs Ok"
    else:
        ocorrencia = ""
        protocolo_id = ""
        origem_documento = ""
        saldo_devedor_um = ""
        contrato_um = ""
        classificacao = "Sinistro não encontrado no MongoDB"

    resultados.append({
        "CPF": cpf,
        "Produto": cd_produto,
        "Nome Produto": nm_produto,
        "Sinistro": nr_sinistro,
        "Apólice": cd_apolice,
        "Endosso": id_endosso,
        "Data Sistema": data_sistema,
        "ID Pessoa Sinistrado": id_pessoa_sinistrado,
        "Ocorrencia": ocorrencia,
        "Protocolo": protocolo_id,
        "Origem Documento": origem_documento,
        "Saldo Devedor Um": saldo_devedor_um,
        "Contrato Um": contrato_um,
        "Classificação": classificacao
    })

df = pd.DataFrame(resultados)
df.to_excel("resultados.xlsx", index=False)
