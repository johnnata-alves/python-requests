import pandas as pd
from collections import Counter

with open('cancelamentos.txt', 'r', encoding='utf-8') as file:
    lines = file.readlines()

def categorize_reason(line):
    if 'Sinistro já registrado' in line.lower():
        return 'Sinistro já registrado'
    elif 'sinistro já tratado' in line.lower():
        return 'Sinistro já registrado'
    elif 'duplcidiade' in line.lower():
        return 'Sinistro já registrado'
    elif 'duplicidade' in line.lower():
        return 'Sinistro já registrado'
    elif 'duplciidade' in line.lower():
        return 'Sinistro já registrado'
    elif 'existe sinistro cadastrado com as mesmas' in line.lower():
        return 'Sinistro já registrado'
    elif 'duplicicdade' in line.lower():
        return 'Sinistro já registrado'
    elif 'já tratado' in line.lower():
        return 'Sinistro já registrado'
    elif 'sinistro sendo tratado' in line.lower():
        return 'Sinistro já registrado'
    elif 'já regulado' in line.lower():
        return 'Sinistro já registrado'
    elif 'aberto pelo i4 pro' in line.lower():
        return 'Sinistro já registrado'
    elif 'sinistro aberto' in line.lower():
        return 'Sinistro já registrado'
    elif 'sendo tratado' in line.lower():
        return 'Sinistro já registrado'
    elif 'já aberto' in line.lower():
        return 'Sinistro já registrado'
    elif 'sendo tratado' in line.lower():
        return 'Sinistro já registrado'
    elif 'dupclidiade' in line.lower():
        return 'Sinistro já registrado'
    elif 'duplicado' in line.lower():
        return 'Sinistro já registrado'
    elif 'teste' in line.lower():
        return 'Teste cancelamento'
    elif 'assistencia' in line.lower():
        return 'Assistência'
    elif 'assistência' in line.lower():
        return 'Assistência'
    elif 'tratado com carta' in line.lower():
        return 'Tratado como carta Adm'
    elif 'falta de dados' in line.lower():
        return 'Erros de dados'
    elif 'carta adm' in line.lower():
        return 'Tratado como carta Adm'
    elif 'apólice não encontrada' in line.lower():
        return 'Apólice não encontrada'
    elif 'não foi possivel selecionar apólice' in line.lower():
        return 'Apólice não encontrada'
    elif 'segurado não encontrado' in line.lower():
        return 'Segurado não encontrado'
    elif 'tratado por e-mail' in line.lower():
        return 'Tratado por e-mail'
    elif 'lista de documentos do sinistro não foi gerada' in line.lower():
        return 'Lista de docsdo não gerada'
    else:
        return 'Outros'

categories = [categorize_reason(line) for line in lines]

count = Counter(categories)
total = sum(count.values())

df = pd.DataFrame(count.items(), columns=['Motivo de Cancelamento', 'Ocorrências'])
df['Percentual (%)'] = (df['Ocorrências'] / total) * 100

outros_items = [line for line, category in zip(lines, categories) if category == 'Outros']

print("\nItens classificados como 'Outros':")
for item in outros_items:
    print(item.strip())

print("Motivo de Cancelamento - Resumo:")
print(df)
