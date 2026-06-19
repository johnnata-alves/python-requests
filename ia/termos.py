import pandas as pd

df = pd.read_excel('sua_planilha.xlsx')

output_lines = []

for index, row in df.iterrows():
    palavra = row['palavra']
    for i in range(1, 6):
        termo = row[f'termo {i}']
        if pd.notna(termo):
            output_lines.append(f"{palavra} = {termo}")

with open('saida.txt', 'w', encoding='utf-8') as file:
    for line in output_lines:
        file.write(line + '\n')

print("Arquivo 'saida.txt' criado com sucesso.")
