import os
import requests
import pyodbc
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

I4PRO_ERP_URL = os.getenv("I4PRO_ERP_URL")

def realizar_chamada_curl(dados):
    url = f"{I4PRO_ERP_URL}/run/InserirFollowupSinistro/InserirFollowupSinistro"
    headers = {
        'Content-Type': 'application/json'
    }
    response = requests.post(url, json=dados, headers=headers)

    if response.status_code == 200:
        print("Follow-up inserido com sucesso!")
    else:
        print("Erro ao inserir follow-up:", response.text)

conn_str = os.getenv("SQL_CONNECTION_I4PRO_PRD")
conn = pyodbc.connect(conn_str)
cursor = conn.cursor()

sinistros = [ 1007700087731,1007700087732,1007700087733,1007700087745,1007700087755,1007700087756,1007700087757,1007700087766,1007700087784,1007700087785,1007700087786,1007700087788,1007700087793,1007700087794,1007700087806,1007700087809,1007700087836,1007700087848,1007700087850,1007700087907,1007700087930,1007700087933,1007700087946,1009300044606,1009300046227,1009300046228,1009300046234,1009300046238,1009300046239,1009300046240,1009300046242,1009300046244,1009300046245,1009300046247,1009300046250,1009300046254,1009300046255,1009300046257,1009300046258,1009300046269,1009300046279,1009300046280,1009300046281,1009300046286,1009300046287,1009300046291,1009300046292,1009300046298,1009300046301,1009300046307,1009300046308,1009300046309,1009300046311,1009300046312,1009300046315,1009300046316,1009300046321,1009300046322,1009300046324,1009300046325,1009300046328,1009300046329,1009300046331,1009300046332,1009300046336,1009300046339,1009300046340,1009300046341,1009300046342,1009300046346,1009300046350,1009300046351,1009300046352,1009300046353,1009300046354,1009300046355,1009300046356,1009300046362,1009300046363,1009300046366,1009300046368,1009300046369,1009300046370,1009300046371,1009300046372,1009300046373,1009300046374,1009300046375,1009300046376,1009300046384,1009300046387,1009300046394,1009300046396,1009300046398,1009300046403,1009300046404,1009300046406,1009300046411,1009300046412,1009300046418,1009300046420,1009300046421,1009300046424,1009300046425,1009300046426,1009300046428,1009300046430,1009300046436,1009300046444,1009300046448,1009300046450,1009300046452,1009300046453,1009300046454,1009300046455,1009300046456,1009300046457,1009300046459,1009300046460,1009300046461,1009300046462,1009300046463,1009300046464,1009300046493,1009300046503,1009300046550,1009300046576,1009300046580,1009300046581,1009300046582,1009300046583,1009300046604,1009300046633,1009300046651,1009300046653,1009300046655,1009300046656,1009300046657,1009300046658,1009300046688,1009300046690,1009300046691,1009300046692,1009300046693,1009300046694,1009300046695,1009300046696,1009300046697,1009300046698,1009300046699,1009300046700,1009300046702,1009300046706,1009300046707,1009300046708,1009300046709
]

for nr_sinistro in sinistros:

    cursor.execute(f"select id_tp_followup, ds_folowup from i4pro_erp..corp_sin_folowup where id_tp_followup in (3,21, 70) and nr_sinistro = {nr_sinistro}")
    resultado = cursor.fetchall()

    tem_id_tp_followup_70 = False
    tem_id_tp_followup_21 = False
    ds_followup = None

    for linha in resultado:
        id_tp_followup = linha[0]
        if id_tp_followup == 3:
            ds_followup = linha[1]

        if id_tp_followup == 70:
            tem_id_tp_followup_70 = True
        elif id_tp_followup == 21:
            tem_id_tp_followup_21 = True

    if not tem_id_tp_followup_70:
        print(f'Sinistro {nr_sinistro} - 70 - OK')
        dados = {
            "cdOperacao": 1,
            "cdUsuarioDestinatario": "UsoFuturo",
            "dtFollowup": datetime.now().isoformat(),
            "dsFollowup": "Documentação para aviso de Sinistro \n Documentos recebidos, data de recebimento e origem do recebimento no momento do aviso",
            "idSinTpInformacao": 2,
            "idTpFollowup": 70,
            "nrSinistro": nr_sinistro,
            "cdUsuario": "usr_sinistro_triagem"
        }
        realizar_chamada_curl(dados)

    if not tem_id_tp_followup_21 and ds_followup is not None:
        print(f'Sinistro {nr_sinistro} - 21 - OK')
        dados = {
            "cdOperacao": 1,
            "cdUsuarioDestinatario": "UsoFuturo",
            "dtFollowup": datetime.now().isoformat(),
            "dsFollowup": ds_followup,
            "idSinTpInformacao": 2,
            "idTpFollowup": 21,
            "nrSinistro": nr_sinistro,
            "cdUsuario": "usr_sinistro_triagem"
        }
        realizar_chamada_curl(dados)

    print(f'Sinistro {nr_sinistro} - OK')

conn.close()
