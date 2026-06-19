import sys
import time

def mostrar_barra_progresso(percentual, total_width=50):
    filled_length = int(total_width * percentual // 100)
    bar = '█' * filled_length + '-' * (total_width - filled_length)  
    sys.stdout.write(f'\r🔍 Arquivo {documento["TipificacaoId"]} sem atualizações! [{bar}] {percentual:.2f}%')
    sys.stdout.flush()

cont = 100
count_atualizar = 45
percentual = (count_atualizar / cont) * 100

for _ in range(10):
    mostrar_barra_progresso(percentual)
    time.sleep(0.5)

print(f"\n✅ Processo concluído para o arquivo {documento['TipificacaoId']}!")
