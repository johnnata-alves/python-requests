import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import pyodbc
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

SQL_CONN_STR = os.getenv("SQL_CONNECTION_I4PRO_PRD")
MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")

client_mongo = MongoClient(MONGO_URI)
db = client_mongo["SinistrosMicroService"]
col_aviso = db["AvisoSinistro"]
col_cobertura_config = db["CoberturaConfiguracao"]

SQL_QUERY_TEMPLATE = """
SELECT TOP 1000
    a.nr_sinistro,
    CAST(a.dt_ocorrencia AS DATE) AS dt_ocorrencia,
    RIGHT('00000000000' + CAST(c.nr_cnpj_cpf AS VARCHAR), 11) as nr_cnpj_cpf,
    d.id_cobertura,
    f.id_grupo_cobertura
FROM corp_sinistro a WITH(NOLOCK)
INNER JOIN corp_sin_movto b WITH(NOLOCK) ON a.nr_sinistro = b.nr_sinistro AND b.cd_evento = 10101
INNER JOIN corp_pessoas c WITH(NOLOCK) ON a.id_pessoa_sinistrado = c.id_pessoa
INNER JOIN corp_produto_cobertura d WITH(NOLOCK) ON b.id_produto_cobertura = d.id_produto_cobertura
INNER JOIN corp_endosso e WITH(NOLOCK) ON e.id_endosso = a.id_endosso
INNER JOIN corp_sub_estipulante cse WITH(NOLOCK) ON e.id_sub = cse.id_sub
INNER JOIN corp_apolice ca WITH(NOLOCK) ON cse.id_apolice = ca.id_apolice
LEFT JOIN corp_grupo_produto_cobertura f WITH(NOLOCK) ON b.id_produto_cobertura = f.id_produto_cobertura AND f.dv_vincular = 1
WHERE ca.id_ramo NOT IN (33)
AND a.nr_sinistro  = 1006100018610

ORDER BY a.nr_sinistro DESC
"""

OUTPUT_FILE = "relatorio_vinculacao_sinistros.xlsx"
WORKERS = int(os.getenv("WORKERS", "10"))
lock = threading.Lock()

SQL_COUNT_QUERY = """
SELECT COUNT(*)
FROM corp_sinistro a WITH(NOLOCK)
INNER JOIN corp_sin_movto b WITH(NOLOCK) ON a.nr_sinistro = b.nr_sinistro AND b.cd_evento = 10101
INNER JOIN corp_pessoas c WITH(NOLOCK) ON a.id_pessoa_sinistrado = c.id_pessoa
INNER JOIN corp_produto_cobertura d WITH(NOLOCK) ON b.id_produto_cobertura = d.id_produto_cobertura
INNER JOIN corp_endosso e WITH(NOLOCK) ON e.id_endosso = a.id_endosso
INNER JOIN corp_sub_estipulante cse WITH(NOLOCK) ON e.id_sub = cse.id_sub
INNER JOIN corp_apolice ca WITH(NOLOCK) ON cse.id_apolice = ca.id_apolice
LEFT JOIN corp_grupo_produto_cobertura f WITH(NOLOCK) ON b.id_produto_cobertura = f.id_produto_cobertura AND f.dv_vincular = 1
WHERE ca.id_ramo NOT IN (33) and a.nr_sinistro  = 1006100018610
"""

def normalizar_cpf(cpf):
    if cpf is None:
        return ""
    valor = str(cpf).strip()
    if valor.endswith(".0"):
        valor = valor[:-2]
    limpo = valor.replace(".", "").replace("-", "").replace("/", "").replace(" ", "")
    if len(limpo) <= 11:
        return limpo.zfill(11)
    return limpo.zfill(14)

def data_sem_hora(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.date()
    return dt

def ja_vinculado(nr_sinistro):
    sinistro_str = str(nr_sinistro)
    doc = col_aviso.find_one({"Sinistros": sinistro_str})
    return doc

def buscar_por_cpf(cpf):
    cpf_limpo = normalizar_cpf(cpf)
    return list(col_aviso.find({"Segurado.CpfCnpj": cpf_limpo}))

def match_caso_1(aviso, id_grupo_cobertura):
    origem = (aviso.get("InformacoesComplementares") or {}).get("origemdocumento", "")
    if "Aviso API" in origem:
        return False
    coberturas = aviso.get("Coberturas") or []
    for cob in coberturas:
        if cob.get("GrupoCoberturaId") == 5 and id_grupo_cobertura == 5:
            return True
    return False

def match_caso_2(aviso, id_grupo_cobertura, id_cobertura, dt_ocorrencia):
    origem = (aviso.get("InformacoesComplementares") or {}).get("origemdocumento", "")
    if "Aviso API" in origem:
        return False
    ocorrencia_aviso = data_sem_hora(aviso.get("Ocorrencia"))
    dt_oc = data_sem_hora(dt_ocorrencia)
    if ocorrencia_aviso != dt_oc:
        return False
    coberturas = aviso.get("Coberturas") or []
    for cob in coberturas:
        grupo = cob.get("GrupoCoberturaId")
        cob_id = cob.get("_id")
        if grupo != 5:
            if grupo == id_grupo_cobertura:
                return True
            if cob_id == id_cobertura:
                return True
    return False

def match_caso_3(aviso, id_grupo_cobertura, id_cobertura, dt_ocorrencia):
    origem = (aviso.get("InformacoesComplementares") or {}).get("origemdocumento", "")
    if "Aviso API" not in origem:
        return False
    ocorrencia_aviso = data_sem_hora(aviso.get("Ocorrencia"))
    dt_oc = data_sem_hora(dt_ocorrencia)
    if ocorrencia_aviso != dt_oc:
        return False
    coberturas = aviso.get("Coberturas") or []
    for cob in coberturas:
        cob_id = cob.get("_id")
        configs = list(col_cobertura_config.find({"CoberturaId": cob_id}))
        for config in configs:
            coberturas_integracao = config.get("CoberturasIntegracao") or []
            for ci in coberturas_integracao:
                if ci.get("GrupoCoberturaId") == id_grupo_cobertura:
                    return True
                if ci.get("CoberturaId") == id_cobertura:
                    return True
    return False

def vincular_sinistro(aviso, nr_sinistro):
    sinistro_str = str(nr_sinistro)
    sinistros_atuais = aviso.get("Sinistros") or []
    if sinistro_str not in sinistros_atuais:
        sinistros_atuais.append(sinistro_str)
        col_aviso.update_one(
            {"_id": aviso["_id"]},
            {"$set": {"Sinistros": sinistros_atuais}}
        )

def carregar_relatorio_existente():
    if os.path.exists(OUTPUT_FILE):
        return pd.read_excel(OUTPUT_FILE).to_dict("records")
    return []

def salvar_relatorio(relatorio):
    df = pd.DataFrame(relatorio)
    df.to_excel(OUTPUT_FILE, index=False)

def obter_ultimo_sinistro(relatorio):
    if not relatorio:
        return None
    sinistros = [r["nr_sinistro"] for r in relatorio if r.get("nr_sinistro")]
    return min(sinistros) if sinistros else None

def construir_query(ultimo_sinistro):
    if ultimo_sinistro is None:
        return SQL_QUERY_TEMPLATE.format(ultimo_sinistro=9999999999999)
    return SQL_QUERY_TEMPLATE.format(ultimo_sinistro=ultimo_sinistro)

def main():
    print("=" * 60)
    print("VINCULAÇÃO DE SINISTROS - PROCESSAMENTO EM LOTES DE 1000")
    print("=" * 60)

    print("\nConsultando total de registros no SQL...")
    sql_conn = pyodbc.connect(SQL_CONN_STR)
    total_geral = pd.read_sql(SQL_COUNT_QUERY, sql_conn).iloc[0, 0]
    sql_conn.close()
    print(f"Total geral de sinistros: {total_geral}")

    relatorio = carregar_relatorio_existente()
    if relatorio:
        print(f"Relatório existente carregado: {len(relatorio)} registros já processados ({round(len(relatorio)/total_geral*100, 1)}%)")

    lote = 1
    while True:
        ultimo_sinistro = obter_ultimo_sinistro(relatorio)
        query = construir_query(ultimo_sinistro)

        pct_geral = round(len(relatorio) / total_geral * 100, 1) if total_geral > 0 else 0
        print(f"\n{'─' * 40}")
        print(f"LOTE {lote} | Processados: {len(relatorio)}/{total_geral} ({pct_geral}%) | Cursor: < {ultimo_sinistro or 'MAX'}")
        print(f"{'─' * 40}")
        print("Consultando SQL Server...")

        sql_conn = pyodbc.connect(SQL_CONN_STR)
        df = pd.read_sql(query, sql_conn)
        sql_conn.close()

        if df.empty:
            print("Nenhum registro novo encontrado. Processamento concluído.")
            break

        print(f"Registros retornados neste lote: {len(df)}")

        def processar_registro(row):
            nr_sinistro = row["nr_sinistro"]
            dt_ocorrencia = row["dt_ocorrencia"]
            cpf = row["nr_cnpj_cpf"]
            id_cobertura = row["id_cobertura"]
            id_grupo_cobertura = row["id_grupo_cobertura"]

            existente = ja_vinculado(nr_sinistro)
            if existente:
                return {
                    "nr_sinistro": nr_sinistro,
                    "acao": "JA_VINCULADO",
                    "protocolo": existente.get("Protocolo", ""),
                    "motivo": "Sinistro já existia na lista de Sinistros"
                }

            cpf_limpo = normalizar_cpf(cpf)
            avisos = buscar_por_cpf(cpf)
            if not avisos:
                print(f"  [NAO_ENCONTRADO] nr_sinistro={nr_sinistro} cpf={cpf_limpo}")
                return {
                    "nr_sinistro": nr_sinistro,
                    "acao": "NAO_ENCONTRADO",
                    "protocolo": "",
                    "motivo": f"Nenhum AvisoSinistro com CPF {cpf_limpo}"
                }

            for aviso in avisos:
                if match_caso_1(aviso, id_grupo_cobertura):
                    vincular_sinistro(aviso, nr_sinistro)
                    print(f"  [VINCULADO] nr_sinistro={nr_sinistro} -> protocolo={aviso.get('Protocolo', '')} (caso 1)")
                    return {
                        "nr_sinistro": nr_sinistro,
                        "acao": "VINCULADO",
                        "protocolo": aviso.get("Protocolo", ""),
                        "motivo": "Match caso 1: GrupoCoberturaId=5 sem Aviso API"
                    }

                if match_caso_2(aviso, id_grupo_cobertura, id_cobertura, dt_ocorrencia):
                    vincular_sinistro(aviso, nr_sinistro)
                    print(f"  [VINCULADO] nr_sinistro={nr_sinistro} -> protocolo={aviso.get('Protocolo', '')} (caso 2)")
                    return {
                        "nr_sinistro": nr_sinistro,
                        "acao": "VINCULADO",
                        "protocolo": aviso.get("Protocolo", ""),
                        "motivo": "Match caso 2: GrupoCoberturaId/id_cobertura + dt_ocorrencia sem Aviso API"
                    }

                if match_caso_3(aviso, id_grupo_cobertura, id_cobertura, dt_ocorrencia):
                    vincular_sinistro(aviso, nr_sinistro)
                    print(f"  [VINCULADO] nr_sinistro={nr_sinistro} -> protocolo={aviso.get('Protocolo', '')} (caso 3)")
                    return {
                        "nr_sinistro": nr_sinistro,
                        "acao": "VINCULADO",
                        "protocolo": aviso.get("Protocolo", ""),
                        "motivo": "Match caso 3: Aviso API + CoberturaConfiguracao + dt_ocorrencia"
                    }

            print(f"  [SEM_MATCH] nr_sinistro={nr_sinistro} cpf={cpf_limpo} avisos_encontrados={len(avisos)}")
            return {
                "nr_sinistro": nr_sinistro,
                "acao": "SEM_MATCH",
                "protocolo": "",
                "motivo": f"Nenhum aviso correspondente para CPF {cpf_limpo}"
            }

        rows = [row for _, row in df.iterrows()]
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(processar_registro, row): row for row in rows}
            for future in tqdm(as_completed(futures), total=len(futures), desc=f"Lote {lote}"):
                try:
                    resultado = future.result()
                    with lock:
                        relatorio.append(resultado)
                except Exception as e:
                    row = futures[future]
                    print(f"  [ERRO] nr_sinistro={row['nr_sinistro']}: {e}")
                    with lock:
                        relatorio.append({
                            "nr_sinistro": row["nr_sinistro"],
                            "acao": "ERRO",
                            "protocolo": "",
                            "motivo": str(e)
                        })

        salvar_relatorio(relatorio)
        pct_pos_lote = round(len(relatorio) / total_geral * 100, 1) if total_geral > 0 else 0
        print(f"Relatório atualizado: {OUTPUT_FILE} ({len(relatorio)}/{total_geral} - {pct_pos_lote}%)")
        lote += 1

    salvar_relatorio(relatorio)
    print(f"\n{'=' * 60}")
    print("RESUMO FINAL")
    print(f"{'=' * 60}")
    print(f"Total processados: {len(relatorio)}")
    print(f"  Já vinculados: {sum(1 for r in relatorio if r['acao'] == 'JA_VINCULADO')}")
    print(f"  Vinculados agora: {sum(1 for r in relatorio if r['acao'] == 'VINCULADO')}")
    print(f"  Sem match: {sum(1 for r in relatorio if r['acao'] == 'SEM_MATCH')}")
    print(f"  Não encontrados: {sum(1 for r in relatorio if r['acao'] == 'NAO_ENCONTRADO')}")
    print(f"Relatório: {OUTPUT_FILE}")

    client_mongo.close()

if __name__ == "__main__":
    main()
