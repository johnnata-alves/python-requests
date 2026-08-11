"""
Método utilitário que recebe um número de sinistro e retorna do SQL (I4Pro):
- idItem
- idProdutoCobertura
- idSinistrado (id_pessoa do sinistrado)
"""

import os
import pyodbc
from dotenv import load_dotenv

load_dotenv()

SQL_CONNECTION = os.getenv("SQL_CONNECTION_I4PRO_PRD_V2")

QUERY = """
SELECT DISTINCT
    ce.id_endosso AS idEndosso,
    csin.nr_item AS idItem,
    mvto.id_produto_cobertura AS idProdutoCobertura,
    csin.id_pessoa_sinistrado AS idSinistrado,
    pess.nr_cnpj_cpf AS cpfSinistrado,
    pess.nm_pessoa AS nomeSinistrado,
    cp.cd_produto AS idProduto,
    cp.nm_produto AS nomeProduto,
    cob.id_cobertura AS idCobertura,
    cob.nm_cobertura AS nomeCobertura,
    ca.cd_apolice AS cdApolice,
    rm.nr_ramo AS idRamo
FROM
    i4pro_erp..corp_sinistro csin WITH(NOLOCK)
    INNER JOIN i4pro_erp..corp_sin_movto mvto WITH(NOLOCK)
        ON csin.nr_sinistro = mvto.nr_sinistro AND mvto.cd_evento = 10101
    INNER JOIN i4pro_erp..corp_endosso ce WITH(NOLOCK)
        ON csin.id_endosso = ce.id_endosso
    INNER JOIN i4pro_erp..corp_sub_estipulante cse WITH(NOLOCK)
        ON ce.id_sub = cse.id_sub
    INNER JOIN i4pro_erp..corp_apolice ca WITH(NOLOCK)
        ON cse.id_apolice = ca.id_apolice
    INNER JOIN i4pro_erp..corp_produto_cobertura cpp WITH(NOLOCK)
        ON mvto.id_produto_cobertura = cpp.id_produto_cobertura
    INNER JOIN i4pro_erp..corp_produto cp WITH(NOLOCK)
        ON cp.cd_produto = cpp.cd_produto
    INNER JOIN i4pro_erp..corp_cobertura cob WITH(NOLOCK)
        ON cob.id_cobertura = cpp.id_cobertura
    INNER JOIN i4pro_erp..corp_ramo rm WITH(NOLOCK)
        ON csin.id_ramo = rm.id_ramo
    INNER JOIN i4pro_erp..corp_pessoas pess WITH(NOLOCK)
        ON pess.id_pessoa = csin.id_pessoa_sinistrado
WHERE
    csin.nr_sinistro = ?
"""


def buscar_dados_sinistro(nr_sinistro, conn_string=None):
    """
    Retorna dict com dados do sinistro ou None se não encontrado.

    Campos retornados:
        idEndosso, idItem, idProdutoCobertura, idSinistrado,
        cpfSinistrado, nomeSinistrado, idProduto, nomeProduto,
        idCobertura, nomeCobertura, cdApolice, idRamo
    """
    conn_str = conn_string or SQL_CONNECTION
    if not conn_str:
        raise ValueError("SQL_CONNECTION_I4PRO_PRD_V2 não configurada no .env")

    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    cursor.execute(QUERY, int(nr_sinistro))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return None

    return {
        "idEndosso": row.idEndosso,
        "idItem": row.idItem,
        "idProdutoCobertura": row.idProdutoCobertura,
        "idSinistrado": row.idSinistrado,
        "cpfSinistrado": row.cpfSinistrado,
        "nomeSinistrado": row.nomeSinistrado,
        "idProduto": row.idProduto,
        "nomeProduto": row.nomeProduto,
        "idCobertura": row.idCobertura,
        "nomeCobertura": row.nomeCobertura,
        "cdApolice": row.cdApolice,
        "idRamo": row.idRamo,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python buscar_dados_sinistro_sql.py <nr_sinistro>")
        sys.exit(1)

    nr = sys.argv[1]
    resultado = buscar_dados_sinistro(nr)

    if resultado:
        for k, v in resultado.items():
            print(f"  {k}: {v}")
    else:
        print(f"Sinistro {nr} não encontrado no SQL.")
