import requests
import json

sinistros = [

    # 1009900010003,
    1009900010004,
    1009900010005,
    1009900010006,
    1009900010007,
    1009900010008,
    1009900010009,
    1009900010010,
    1009900010011,
    1009900010012,
    1009900010013,
    1009900010014,
    1009900010015,
    1009900010016,
    1009900010017,
    1009900010018,
    1009900010019,
    1009900010020

]

for nr_sinistro in sinistros:
    consulta_url = 'http://i4pro/i4protoo_prd/erpws/run/Sinistro/ConsultaDetalheSinistro'
    payload = json.dumps({"numSinistro": nr_sinistro})
    headers = {'Content-Type': 'application/json'}

    response = requests.post(consulta_url, headers=headers, data=payload)
    if response.status_code != 200:
        print(f"Erro ao consultar o sinistro {nr_sinistro}")
        continue

    data = response.json()

    aviso_movimento = None
    for mov in data.get('movimentos', []):
        if mov.get('evento') == 'Aviso':
            aviso_movimento = mov
            break

    if aviso_movimento is None:
        print(f"Sem movimento de aviso para o sinistro {nr_sinistro}")
        continue


    alterar_url = 'http://i4pro/i4protoo_prd/erpws/run/AlterarDetalheSinistro/alterarDetalheSinistro'
    dados_alterar = {
        "nrSinistro": nr_sinistro,
        "cdStatus": 801,
        "cdTpCausa": 2,
        "cdCausa": 15033,
        "cdUfOcorrencia": 1,
        "nmCidadeOcorrencia": "São Paulo",
        "cdUsuario": "usr_sinistro_motor"
    }
    resp_alterar = requests.post(alterar_url, headers=headers, data=json.dumps(dados_alterar))
    if resp_alterar.status_code != 200:
        print(f"Erro ao alterar status do sinistro {nr_sinistro}")
        continue

    valor = aviso_movimento['valor']

    registrar_url = 'http://i4pro/i4protoo_prd/erpws/run/RegistrarEventoSinistro/registrarEventoSinistro'
    dados_registrar = {
        "cdEvento": 10105,
        "numSinistro": nr_sinistro,
        "cdUsuario": "usr_sinistro_motor",
        "nmObs": "Sinistro aberto incorretamente",
        "vlOperacao": float(valor),
        "idTpMotivo": 72
    }
    resp_registrar = requests.post(registrar_url, headers=headers, data=json.dumps(dados_registrar))
    if resp_registrar.status_code != 200:
        print(f"Erro ao registrar evento para o sinistro {nr_sinistro}")
        continue



    print(f"Processado sinistro {nr_sinistro}")
