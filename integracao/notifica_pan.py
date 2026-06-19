import os
from dotenv import load_dotenv
import uuid
from datetime import datetime

import pyodbc
from bson.int64 import Int64
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DB_MONGO = "SinistrosMicroService"

SQL_CONN = os.getenv("SQL_CONNECTION_I4PRO_PRD")

protocolos = [
    "02202561803404585",
"02202562003409321",
"02202562503423858",
"02202562503423869",
"02202562503424011",
"02202562603427868",
"02202562603427923",
"02202562603427955",
"0220256603360616",
"02202571003479927",
"02202571003479952",
"02202571003479972",
"02202571003479974",
"02202571003480009",
"02202571003480039",
"02202571003480046",
"02202571003480069",
"02202571003480097",
"02202571003480104",
"02202571003480156",
"02202571003480161",
"02202571003480170",
"02202571003480198",
"02202571003480208",
"02202571103484730",
"02202571103484906",
"02202571703506768",
"02202571703506834",
"0220257303451998",
"02202581303594189",
"02202582003618471",
"02202582003618568",
"02202582003618596",
"02202582703642234",
"02202582703642292",
"02202582803647578",
"02202591003688695",
"02202591003688740",
"02202591003688758",
"02202591003688794",
"02202591003688819",
"02202591003688833",
"02202591003688874",
"02202591003688879",
"02202591703712703",
"02202591803716606",
"02202591803716612",
"02202591803716737",
"02202592403735268",
"02202592403735291",
"02202592403735310",
"02202592403735328",
"02202592403735340",
"02202592403735352",
"02202592403735453",
"02202592403735502",
"0220259303665904",
"0220259303665932",
"0220259303665966",
"0220259403670097",
"0220259403670229",
"0220259403670260"
]

mongo = MongoClient(MONGO_URI)
db = mongo[DB_MONGO]

collection_aviso = db["AvisoSinistro"]
collection_timeline = db["SinistroTimeline"]

sql_conn = pyodbc.connect(SQL_CONN)
cursor = sql_conn.cursor()

SQL_QUERY = """
SELECT distinct
    csin.nr_sinistro,
    ca.cd_produto,
    csin.dt_ocorrencia,
    ca.cd_apolice,
    REPLICATE('0', 11 - LEN(CONVERT(varchar,cp.nr_cnpj_cpf))) + CONVERT(varchar,cp.nr_cnpj_cpf) AS cpf ,
    RTRIM(LTRIM(civ.nr_chave_externa)) as numeroBilhete,
    f.id_grupo_cobertura,
    prod_c.id_cobertura,
    prod.nm_produto,
    rm.nr_ramo,
    st.nm_status,
    csin.cd_tp_causa
FROM i4pro_erp..corp_sinistro csin (NOLOCK)
inner join i4pro_erp..corp_endosso_item_vida ceiv with(NOLOCK) on ceiv.id_endosso_item_vida = csin.nr_item
inner join i4pro_erp..corp_item_vida civ with(NOLOCK) on civ.id_pessoa_item = ceiv.id_pessoa_item and csin.id_pessoa_sinistrado = civ.id_pessoa
inner join i4pro_erp..corp_endosso ce (nolock) on csin.id_endosso = ce.id_endosso
inner join i4pro_erp..corp_sub_estipulante cse (nolock) on cse.id_sub = ce.id_sub
inner join i4pro_erp..corp_apolice ca (nolock) on ca.id_apolice = cse.id_apolice
inner join i4pro_erp..corp_pessoas cp (nolock) on csin.id_pessoa_sinistrado = cp.id_pessoa
inner join i4pro_erp..corp_sin_movto b with(NOLOCK) on csin.nr_sinistro = b.nr_sinistro and b.cd_evento = 10101
left join i4pro_erp..corp_grupo_produto_cobertura f with(NOLOCK) on b.id_produto_cobertura = f.id_produto_cobertura and f.dv_vincular = 1
inner join i4pro_erp..corp_produto_cobertura prod_c with(NOLOCK) on b.id_produto_cobertura = prod_c.id_produto_cobertura
inner join i4pro_erp..corp_produto prod with(NOLOCK) on ca.cd_produto = prod.cd_produto
inner join i4pro_erp..corp_ramo rm with(NOLOCK) on rm.id_ramo = csin.id_ramo
inner join i4pro_erp..corp_status st with(NOLOCK) on csin.cd_status = st.cd_status
WHERE cp.nr_cnpj_cpf = ?
AND csin.dt_ocorrencia between ? and ?
"""

for protocolo in protocolos:

    aviso = collection_aviso.find_one({"Protocolo": protocolo})

    if not aviso:
        print(f"Protocolo não encontrado: {protocolo}")
        continue

    cpf = aviso["Segurado"]["CpfCnpj"]
    data_ocorrencia = aviso["Ocorrencia"]

    data_inicio = data_ocorrencia.strftime("%Y-%m-%d")
    data_fim = data_ocorrencia.strftime("%Y-%m-%d 23:59:00")

    cursor.execute(SQL_QUERY, cpf, data_inicio, data_fim)
    rows = cursor.fetchall()

    sinistros = set()
    apolices = []
    produtos = []

    for row in rows:
        nr_sinistro = str(row.nr_sinistro)
        sinistros.add(nr_sinistro)
        numero_certificado = row.numeroBilhete.split("_", 1)[0].strip() if row.numeroBilhete else None
        if not numero_certificado or not numero_certificado.isdigit():
            numero_certificado = 0

        cobertura = {
            "_id": int(row.id_cobertura) if not row.id_grupo_cobertura else 0,
            "GrupoCoberturaId": int(row.id_grupo_cobertura) if row.id_grupo_cobertura else 0,
            "TipoCausaId": int(row.cd_tp_causa),
            "SaldoDevedor": None
        }

        apolice = {
            "NumeroApolice": int(row.cd_apolice),
            "NumeroSinistro": nr_sinistro,
            "NumeroCertificado": numero_certificado,
            "DataContrato": None,
            "Placa": None,
            "Coberturas": [cobertura]
        }

        apolices.append(apolice)

        produtos.append({
            "Codigo": Int64(row.cd_produto),
            "RamoId": int(row.nr_ramo),
            "NumeroSinistro": nr_sinistro,
            "Descricao": row.nm_produto,
            "Apolices": [{
                **apolice,
                "Status": row.nm_status,
                "StatusResumido": "Sinistro concluído"
            }]
        })

    collection_aviso.update_one(
        {"Protocolo": protocolo},
        {
            "$set": {
                "Sinistros": list(sinistros),
                "Apolices": apolices,
                "Produtos": produtos
            }
        }
    )

    for sinistro in sinistros:

        filtro = {
            "Protocolo": protocolo,
            "NumeroSinistro": sinistro,
            "Codigo": "20002",
            "NotificaParceiro": True
        }

        existe = collection_timeline.find_one(filtro)

        if not existe:
            agora = datetime.utcnow()

            collection_timeline.insert_one({
                "_id": str(uuid.uuid4()),
                "Protocolo": protocolo,
                "NumeroSinistro": sinistro,
                "Apolice": None,
                "Codigo": "20002",
                "Tipo": "sistema",
                "NotificaParceiro": True,
                "ParceiroNotificado": False,
                "Descricao": "Sinistro Aberto",
                "DataEvento": agora,
                "DataInclusao": agora,
                "DataVencimento": None,
                "DataConclusao": None,
                "InformacaoAdicional": {
                    "Indenizacao": None,
                    "StatusSinistroAlterado": None,
                    "Detalhes": []
                },
                "StatusResumido": None,
                "Processado": False,
                "ReturnCode": None,
                "ReturnName": None,
                "Usuario": None
            })

    data_atual = datetime.now()

    collection_timeline.update_many(
        {
            "Protocolo": protocolo,
            "NotificaParceiro": True
        },
        {
            "$set": {
                "Processado": False,
                "ParceiroNotificado": False,
                "DataEvento": data_atual,
                "DataInclusao": data_atual
            }
        }
    )

    print(f"Processado protocolo {protocolo}")
