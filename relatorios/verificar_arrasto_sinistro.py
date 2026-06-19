import os
import pyodbc
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SQL_CONNECTION = os.getenv("SQL_CONNECTION_I4PRO_PRD")
ARQUIVO_EXCEL = "relatorios/entrada.xlsx"
ABA_ORIGEM = 0
ABA_RESULTADO = "Resultado"
MAX_WORKERS = 10

QUERY = """
select distinct
    REPLICATE('0', 11 - LEN(CONVERT(varchar,cp.nr_cnpj_cpf))) + CONVERT(varchar,cp.nr_cnpj_cpf) AS cpf_com_zero_a_esquerda,
    chave_matricula = civ.nr_chave_externa,
    ca.nr_bilhete,
    codigo_apolice = CONVERT(varchar, ca.cd_apolice),
    codigo_produto = ca.cd_produto,
    ramo = ca.id_ramo,
    css.nm_status,
    css.cd_status,
    cpp.nm_produto,
    ce.dt_inicio_vigencia,
    ce.dt_fim_vigencia,
    civc.vl_is,
    csstt.nm_status as status_sinistro,
    csin.nr_sinistro,
    csin.dt_sistema,
    csin.dt_ocorrencia
from i4pro_erp..corp_pessoas cp with(NOLOCK)
inner join i4pro_erp..corpvw_itens_vida civ with(NOLOCK) on cp.id_pessoa = civ.id_pessoa
inner join i4pro_erp..corp_endosso_item_vida ceiv with(NOLOCK) on ceiv.id_pessoa_item = civ.id_pessoa_item
inner join i4pro_erp..corp_item_vida_cobertura civc with(NOLOCK) on ceiv.id_pessoa_item = civc.id_pessoa_item
inner join i4pro_erp..corp_endosso ce with(NOLOCK) on ceiv.id_endosso = ce.id_endosso and ce.cd_tipo_endosso = 0
inner join i4pro_erp..corp_sub_estipulante cse with(NOLOCK) on ce.id_sub = cse.id_sub
inner join i4pro_erp..corp_apolice ca with(NOLOCK) on cse.id_apolice = ca.id_apolice
inner join i4pro_erp..corp_status css with(NOLOCK) on ca.cd_status = css.cd_status
inner join i4pro_erp..corp_produto cpp with(NOLOCK) on ca.cd_produto = cpp.cd_produto
inner join i4pro_erp..corp_grupo_produto_cobertura cgpc with(NOLOCK) on cgpc.id_produto_cobertura = civc.id_produto_cobertura and cgpc.id_grupo_cobertura = 5 and dv_vincular = 1
left join i4pro_erp..corp_sinistro csin with(NOLOCK) on cp.id_pessoa = csin.id_pessoa_sinistrado and csin.id_endosso = ce.id_endosso
left join i4pro_erp..corp_status csstt with(NOLOCK) on csstt.cd_status = csin.cd_status
where cp.nr_cnpj_cpf = ?
  and ? between ce.dt_inicio_vigencia and ce.dt_fim_vigencia
"""

def format_date_br(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    text = str(value).strip()
    if not text:
        return ""
    try:
        dt = datetime.strptime(text[:10], "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return text

def format_decimal_br(value) -> str:
    if value is None:
        return ""
    return str(value).replace(".", ",")

def query_sql(cpf: str, data_sql: str) -> list:
    """Executa a query SQL e retorna todas as linhas como lista de dicts."""
    conn = pyodbc.connect(SQL_CONNECTION)
    cursor = conn.cursor()
    cursor.execute(QUERY, cpf, data_sql)
    columns = [col[0] for col in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return rows

def format_date_sql(data_ocorrencia) -> str:
    if isinstance(data_ocorrencia, datetime):
        return data_ocorrencia.strftime("%Y-%m-%d")
    try:
        return datetime.strptime(str(data_ocorrencia).strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return str(data_ocorrencia).strip()

def process_cpf(cpf: str, data_sql: str, contratos_origem: set) -> list:
    """Consulta SQL 1x por CPF e gera resultados para todas as linhas retornadas."""
    try:
        sql_rows = query_sql(cpf, data_sql)
    except Exception as e:
        return [{"cpf": cpf, "erro": str(e)[:100]}]

    if not sql_rows:
        return []

    results = []
    for reg in sql_rows:
        chave_matricula = str(reg.get("chave_matricula") or "").strip()
        nr_sinistro = reg.get("nr_sinistro")

        arrasto = "Não" if chave_matricula in contratos_origem else "Sim"

        results.append({
            "cpf": cpf,
            "chave_matricula": chave_matricula,
            "nr_bilhete": str(reg.get("nr_bilhete") or ""),
            "codigo_apolice": str(reg.get("codigo_apolice") or ""),
            "codigo_produto": str(reg.get("codigo_produto") or ""),
            "ramo": str(reg.get("ramo") or ""),
            "status_apolice": str(reg.get("nm_status") or ""),
            "cd_status": str(reg.get("cd_status") or ""),
            "nm_produto": str(reg.get("nm_produto") or ""),
            "dt_inicio_vigencia": format_date_br(reg.get("dt_inicio_vigencia")),
            "dt_fim_vigencia": format_date_br(reg.get("dt_fim_vigencia")),
            "vl_is": format_decimal_br(reg.get("vl_is")),
            "status_sinistro": str(reg.get("status_sinistro") or ""),
            "nr_sinistro": str(nr_sinistro or ""),
            "dt_sistema_sinistro": format_date_br(reg.get("dt_sistema")),
            "dt_ocorrencia_sinistro": format_date_br(reg.get("dt_ocorrencia")),
            "Arrasto": arrasto,
            "SinistroExistente": "Sim" if nr_sinistro else "Não",
        })

    return results

def main():
    print(f"Lendo planilha: {ARQUIVO_EXCEL}")
    df = pd.read_excel(ARQUIVO_EXCEL, sheet_name=ABA_ORIGEM)
    total = len(df)
    print(f"Registros na planilha: {total}")

    contratos_origem = set()
    for val in df["contrato"]:
        contratos_origem.add(str(val).strip())

    cpf_data_map = {}
    for _, row in df.iterrows():
        cpf = str(row["cpf"]).strip()
        data_sql = format_date_sql(row["data de ocorrência"])
        if cpf not in cpf_data_map:
            cpf_data_map[cpf] = data_sql

    cpfs_unicos = list(cpf_data_map.keys())
    print(f"CPFs únicos a consultar: {len(cpfs_unicos)} | Workers: {MAX_WORKERS}")

    all_results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_cpf, cpf, cpf_data_map[cpf], contratos_origem): cpf
            for cpf in cpfs_unicos
        }

        with tqdm(total=len(futures), desc="Consultando SQL") as pbar:
            for future in as_completed(futures):
                rows = future.result()
                all_results.extend(rows)
                pbar.update(1)

    df_resultado = pd.DataFrame(all_results)

    with pd.ExcelWriter(ARQUIVO_EXCEL, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        df_resultado.to_excel(writer, sheet_name=ABA_RESULTADO, index=False)

    print(f"\nResultado salvo na aba '{ABA_RESULTADO}' | Linhas: {len(all_results)}")

    arrasto_sim = sum(1 for r in all_results if r.get("Arrasto") == "Sim")
    arrasto_nao = sum(1 for r in all_results if r.get("Arrasto") == "Não")
    sinistro_sim = sum(1 for r in all_results if r.get("SinistroExistente") == "Sim")
    sem_registro = len(cpfs_unicos) - len(set(r.get("cpf") for r in all_results))
    print(f"Arrasto Sim: {arrasto_sim} | Arrasto Não: {arrasto_nao} | Sinistro Existente: {sinistro_sim} | Sem registro: {sem_registro}")

if __name__ == "__main__":
    main()
