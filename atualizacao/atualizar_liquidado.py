import json

import requests

def atualizar_sinistros(lista_sinistros):

    alterar_url = "http://i4pro.tooseguros.com.br/i4protoo_prd/erpws/run/AlterarDetalheSinistro/alterarDetalheSinistro"

    headers = {
        "Content-Type": "application/json"
    }

    sucesso = 0
    erro = 0

    print(f"Iniciando processamento de {len(lista_sinistros)} sinistros...\n")

    for nr_sinistro in lista_sinistros:

        try:
            dados_alterar = {
                "nrSinistro": nr_sinistro,
                "cdStatus": 447,
                "cdUsuario": "usr_sinistro_motor"
            }

            resp = requests.post(
                alterar_url,
                headers=headers,
                data=json.dumps(dados_alterar),
                timeout=30
            )

            if resp.status_code == 200:
                print(f"[OK] Sinistro {nr_sinistro} atualizado")
                sucesso += 1
            else:
                print(f"[ERRO] Sinistro {nr_sinistro} - StatusCode: {resp.status_code}")
                erro += 1

        except Exception as e:
            print(f"[ERRO] Sinistro {nr_sinistro} - Exception: {str(e)}")
            erro += 1

    print("\nProcessamento finalizado")
    print(f"Sucesso: {sucesso}")
    print(f"Erro: {erro}")

if __name__ == "__main__":

    sinistros = [
"1007700076922",
"1007700076988",
"1007700072682",
"1007700079288",
"1007700072695",
"1007700075744"
    ]

    atualizar_sinistros(sinistros)
