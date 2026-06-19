import os
from dotenv import load_dotenv
import requests
from pymongo import MongoClient
from datetime import datetime

load_dotenv()

MONGODB_URL = os.getenv("PRD_MONGO_SA_EAST")

client = MongoClient(MONGODB_URL)
db = client['SinistrosMicroService']
timeline_db = db['SinistroTimeline']
aviso_db = db['AvisoSinistro']

data_referencia = datetime(2024, 8, 1)

lista_avisos = []
lista_erros = timeline_db.find({ "Descricao": "Falha Envio Regulação Automática", "DataEvento": { "$gt": data_referencia } })
for item in lista_erros:
    resultado_aviso = aviso_db.find_one({ "Protocolo": item.get('Protocolo') })
    lista_avisos.append(resultado_aviso)

client.close()

with open('resultado_dados_apolice.txt', 'w') as arquivo:
    for aviso in lista_avisos:
        cpf = aviso.get('Segurado').get('CpfCnpj')
        ocorrencia = aviso.get('Ocorrencia')
        data_aviso = aviso.get('Criacao')
        url = f"http://i4pro-erp.tooseguros.com.br/i4protoo_prd/erpws/run/ConsultaDadosApolice/dadosApolice?NumCnpjCpfSegurado={cpf}"

        response = requests.get(url)

        if response.status_code == 200:
            dados = response.json()

            for apolice in dados.get('dadosApolice', []):
                qtde_itens = len(apolice.get('endosso').get('dadosEndosso',[]))
                if qtde_itens < 1:
                        arquivo.write(f"CPF: {cpf}, Ocorrencia: {ocorrencia}, Aviso: {data_aviso}, Apolice: {apolice.get('numeroApolice', 'N/A')}, proposta: {apolice.get('numProposta', 'N/A')}, Com endosso vazio\n")

        else:
            print(f"Erro ao consultar CPF {cpf}: {response.status_code}")

print("Processamento concluído. Resultados salvos em 'resultado_dados_apolice.txt'.")
