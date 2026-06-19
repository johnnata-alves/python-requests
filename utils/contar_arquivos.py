import os
import json
import pandas as pd

def contar_registros_em_arquivos_json(diretorio):
    registros_por_arquivo = []

    for nome_arquivo in os.listdir(diretorio):
        caminho_arquivo = os.path.join(diretorio, nome_arquivo)
        
        if os.path.isfile(caminho_arquivo) and nome_arquivo.endswith('.json'):
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                try:
                    dados = json.load(f)
                    quantidade = len(dados)
                    
                    partes = nome_arquivo.split('_')
                    id_arquivo = partes[1]

                    registros_por_arquivo.append({'ID': id_arquivo, 'Contagem': quantidade})

                except json.JSONDecodeError:
                    print(f'Erro ao ler o arquivo JSON: {nome_arquivo}')

    return registros_por_arquivo

diretorio = 'C:\meta'
registros_por_arquivo = contar_registros_em_arquivos_json(diretorio)

df = pd.DataFrame(registros_por_arquivo)

nome_arquivo_excel = 'resultado_contagem_registros.xlsx'
df.to_excel(nome_arquivo_excel, index=False)

print(f'Resultados foram salvos em {nome_arquivo_excel}')
