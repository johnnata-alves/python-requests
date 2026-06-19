import requests
import json

sinistros = [
    1009300059255,
    1002900016518,
    1009300059470,
    1009300062062,
    1009300063620,
    1002900014880,
    1002900015045,
    1002900015613,
    1002900015614,
    1002900015615,
    1002900015616,
    1002900015617,
    1002900015618,
    1002900015619
]

for nr_sinistro in sinistros:
    consulta_url = 'http://i4prosite.dev.tooseguros.com.br/i4pro_dev1/erpws/run/Sinistro/ConsultaDetalheSinistro'
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

    valor = aviso_movimento['valor']
    
    registrar_url = 'http://i4prosite.dev.tooseguros.com.br/i4pro_dev1/erpws/run/RegistrarEventoSinistro/registrarEventoSinistro'
    dados_registrar = {
        "cdEvento": 10105,
        "numSinistro": nr_sinistro,
        "cdUsuario": "usr_sinistro_motor",
        "vlOperacao": float(valor),
        "idTpMotivo": 42
    }
    resp_registrar = requests.post(registrar_url, headers=headers, data=json.dumps(dados_registrar))
    if resp_registrar.status_code != 200:
        print(f"Erro ao registrar evento para o sinistro {nr_sinistro}")
        continue

    alterar_url = 'http://i4prosite.dev.tooseguros.com.br/i4pro_dev1/erpws/run/AlterarDetalheSinistro/alterarDetalheSinistro'
    dados_alterar = {
        "nrSinistro": nr_sinistro,
        "cdStatus": 477,
        "cdUsuario": "usr_sinistro_motor"
    }
    resp_alterar = requests.post(alterar_url, headers=headers, data=json.dumps(dados_alterar))
    if resp_alterar.status_code != 200:
        print(f"Erro ao alterar status do sinistro {nr_sinistro}")
        continue

    print(f"Processado sinistro {nr_sinistro}")
