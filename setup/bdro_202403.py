import pandas as pd
import json
from datetime import datetime

arquivo_excel = 'BDRO-202403.xlsx'
dados_planilha = pd.read_excel(arquivo_excel)

string_columns = ['protocolo', 'identificacaoResponsavel', 'dataAbertura',
                  'dataEncerramento', 'numeroContrato', 'numeroProcessoSusep',
                  'identificacaoReclamante', 'cep']

for col in string_columns:
    if col in dados_planilha.columns:
        dados_planilha[col] = dados_planilha[col].astype(str)

json_output = {
    "entidade": "06653",
    "competencia": "202403",
    "reclamacoes": []
}

def formatar_data(data):
    if isinstance(data, str):
        try:
            return datetime.strptime(data, "%d-%m-%Y").strftime("%d-%m-%Y")
        except ValueError:
            return None
    return None

for index, row in dados_planilha.iterrows():
    reclamacao = {
        "registro": row['registro'] if pd.notna(row['registro']) else None,
        "protocolo": row['protocolo'] if pd.notna(row['protocolo']) else None,
        "identificacaoResponsavel": row['identificacaoResponsavel'] if pd.notna(row['identificacaoResponsavel']) else None,
        "dataAbertura": formatar_data(row['dataAbertura']) if pd.notna(row['dataAbertura']) else None,
        "dataEncerramento": formatar_data(row['dataEncerramento']) if pd.notna(row['dataEncerramento']) else None,
        "numeroContrato": row['numeroContrato'] if pd.notna(row['numeroContrato']) else None,
        "numeroProcessoSusep": row['numeroProcessoSusep'] if pd.notna(row['numeroProcessoSusep']) else None,
        "motivo": row['motivo'] if pd.notna(row['motivo']) else None,
        "canalVenda": row['canalVenda'] if pd.notna(row['canalVenda']) else None,
        "status": row['status'] if pd.notna(row['status']) else None,
        "canalReclamacao": row['canalReclamacao'] if pd.notna(row['canalReclamacao']) else None,
        "assunto": row['assunto'] if pd.notna(row['assunto']) else None,
        "reclamante": {
            "nome": row['nome'] if pd.notna(row['nome']) else None,
            "identificacaoReclamante": row['identificacaoReclamante'] if pd.notna(row['identificacaoReclamante']) else None,
            "sexo": row['sexo'] if pd.notna(row['sexo']) else None,
            "dataNascimento": formatar_data(row['dataNascimento']) if pd.notna(row['dataNascimento']) else None,
            "cep": row['cep'] if pd.notna(row['cep']) else None,
            "tipo": row['tipo'] if pd.notna(row['tipo']) else None
        }
    }
    json_output["reclamacoes"].append(reclamacao)

with open('BDRO-202403.json', 'w', encoding='utf-8') as json_file:
    json.dump(json_output, json_file, indent=4, ensure_ascii=False)

print("JSON gerado com sucesso!")
