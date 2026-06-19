import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DB_NAME = "SinistrosMicroService"
COLLECTION = "ImportEboxItems"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

ARQUIVOS = [
    "eBox_registros_Sinistros_(Auto)_Cobertura_Garantia_Mecanica_134206652949671199.csv",
    "eBox_registros_Sinistros_Seguro_Cartao_Protegido_134206652476068457.csv",
    "eBox_registros_SINISTROS_TOO_Seguros_134206713888839397.csv",
    "eBox_registros_Sinistros_(auto)_Cobertura_Roubo_Furto_134206652965609534.csv",
    "eBox_registros_Sinistros_Cobertura_Danos_Fisicos_ao_Imovel_DFI_134206638972531954.csv",
    "eBox_registros_Sinistros_Cobertura_Desemprego_134206644203881640.csv",
    "eBox_registros_Sinistros_Cobertura_Fianca_134206644229038027.csv",
    "eBox_registros_Sinistros_Cobertura_Incapacidade_134206644862018125.csv",
    "eBox_registros_Sinistros_Cobertura_Invalidez_134206645483593424.csv",
    "eBox_registros_Sinistros_Cobertura_Morte_134206650756818500.csv",
    "eBox_registros_Sinistros_Cobertura_Roubo_Furto_Quebra_134206652027466837.csv",
    "eBox_registros_Sinistros_Outros_134206652243095873.csv",
]

MAX_WORKERS = 4

BATCH_SIZE = 500

print_lock = Lock()

def make_col():
    """Cria uma conexão Mongo independente por thread."""
    c = MongoClient(MONGO_URI)
    return c[DB_NAME][COLLECTION]

def extrair_nome_lote(nome_arquivo: str) -> str:
    """Extrai o nome do lote removendo prefixo e ID numérico do nome do arquivo."""
    sem_ext = os.path.splitext(nome_arquivo)[0]
    sem_prefixo = re.sub(r"^eBox_registros_", "", sem_ext, flags=re.IGNORECASE)
    return re.sub(r"_\d{15,}$", "", sem_prefixo)

def safe_int(valor):
    """Converte para int nativo Python, tolerando float, string e numpy types."""
    try:
        if pd.isna(valor):
            return None
        return int(float(valor))
    except (ValueError, TypeError):
        return str(valor).strip() or None

def processar_arquivo(nome_arquivo: str):
    caminho = os.path.join(SCRIPT_DIR, nome_arquivo)
    nome_lote = extrair_nome_lote(nome_arquivo)
    col = make_col()

    df = pd.read_csv(caminho, encoding="latin-1", sep=";", on_bad_lines="skip", low_memory=False)

    col_registro = next((c for c in df.columns if c.strip().lower() == "registro id"), None)
    col_item     = next((c for c in df.columns if c.strip().lower() == "item id"), None)

    if not col_registro:
        return nome_lote, 0, 0, f"Coluna 'Registro Id' não encontrada. Colunas: {list(df.columns)}"
    if not col_item:
        return nome_lote, 0, 0, f"Coluna 'Item ID' não encontrada. Colunas: {list(df.columns)}"

    df = df[[col_registro, col_item]].dropna(subset=[col_registro]).copy()

    registros_ids = [safe_int(v) for v in df[col_registro].tolist()]
    registros_ids = [r for r in registros_ids if r is not None]

    existentes = col.find(
        {"lote": nome_lote, "registroId": {"$in": registros_ids}},
        {"registroId": 1, "itemId": 1, "_id": 0}
    )
    chaves_existentes = {
        (doc["registroId"], doc.get("itemId"))
        for doc in existentes
    }

    novos = []
    pulados = 0

    for _, row in df.iterrows():
        registro_id = safe_int(row[col_registro])
        item_id = safe_int(row[col_item])

        if registro_id is None:
            continue

        if (registro_id, item_id) in chaves_existentes:
            pulados += 1
            continue

        novos.append({
            "registroId": registro_id,
            "itemId": item_id,
            "lote": nome_lote,
            "arquivo": nome_arquivo,
            "status": "pending",
        })

    inseridos = 0
    erros_batch = 0
    for i in range(0, len(novos), BATCH_SIZE):
        batch = novos[i:i + BATCH_SIZE]
        if not batch:
            continue
        try:
            col.insert_many(batch, ordered=False)
            inseridos += len(batch)
        except Exception:
            for doc in batch:
                try:
                    col.insert_one(doc)
                    inseridos += 1
                except Exception:
                    erros_batch += 1

    if erros_batch:
        return nome_lote, inseridos, pulados, f"{erros_batch} documento(s) falharam no insert"

    return nome_lote, inseridos, pulados, None

def main():
    arquivos_validos = [
        f for f in ARQUIVOS
        if os.path.exists(os.path.join(SCRIPT_DIR, f))
    ]
    ausentes = set(ARQUIVOS) - set(arquivos_validos)
    for f in ausentes:
        print(f"[SKIP] Arquivo não encontrado: {f}")

    print(f"Conectando ao MongoDB: {DB_NAME}.{COLLECTION}")

    col_idx = make_col()
    col_idx.create_index(
        [("registroId", 1), ("itemId", 1), ("lote", 1)],
        name="idx_registroId_itemId_lote",
        background=True,
    )
    col_idx.create_index(
        [("lote", 1), ("status", 1)],
        name="idx_lote_status",
        background=True,
    )
    print("Índices verificados/criados.")
    print(f"Processando {len(arquivos_validos)} arquivo(s) com {MAX_WORKERS} workers paralelos\n")

    total_inseridos = 0
    total_pulados = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(processar_arquivo, f): f for f in arquivos_validos}

        for future in tqdm(as_completed(futures), total=len(futures), desc="Arquivos", unit="arq"):
            nome_arquivo = futures[future]
            try:
                nome_lote, inseridos, pulados, erro = future.result()
                total_inseridos += inseridos
                total_pulados += pulados
                with print_lock:
                    if erro:
                        tqdm.write(f"  [AVISO] {nome_lote}: inseridos={inseridos} | pulados={pulados} | {erro}")
                    else:
                        tqdm.write(f"  {nome_lote}: inseridos={inseridos} | pulados={pulados}")
            except Exception as e:
                with print_lock:
                    tqdm.write(f"  [ERRO] {nome_arquivo}: {e}")

    print(f"\n{'=' * 50}")
    print(f"Total inseridos : {total_inseridos}")
    print(f"Total pulados   : {total_pulados}")
    print(f"{'=' * 50}")

if __name__ == "__main__":
    main()
