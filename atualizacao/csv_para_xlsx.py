"""
Le um CSV e converte para XLSX.
Ajuste CSV_INPUT_FILE / CSV_OUTPUT_FILE / CSV_SEP abaixo.
"""

import csv
from pathlib import Path

import pandas as pd

CSV_INPUT_FILE = "entrada.csv"
CSV_OUTPUT_FILE = None   # None = mesmo nome com .xlsx
CSV_SEP = None           # None = detecta automatico; ou force "," ";" "\t"

EXCEL_MAX_COLS = 16384


def detectar_sep(csv_file: Path) -> str:
    with open(csv_file, "r", encoding="utf-8-sig", newline="") as f:
        amostra = f.read(8192)
    try:
        return csv.Sniffer().sniff(amostra, delimiters=",;\t|").delimiter
    except csv.Error:
        # fallback: separador mais frequente na 1a linha
        primeira = amostra.splitlines()[0] if amostra else ""
        contagem = {s: primeira.count(s) for s in [",", ";", "\t", "|"]}
        return max(contagem, key=contagem.get) or ","


def converter(csv_path: str, xlsx_path: str | None = None, sep: str | None = None) -> str:
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV nao encontrado: {csv_file}")

    saida = Path(xlsx_path) if xlsx_path else csv_file.with_suffix(".xlsx")

    usado = sep or detectar_sep(csv_file)
    print(f"Separador usado: {usado!r}")

    df = pd.read_csv(csv_file, sep=usado, dtype=str, keep_default_na=False, engine="python")

    if df.shape[1] > EXCEL_MAX_COLS:
        raise ValueError(
            f"{df.shape[1]} colunas detectadas (max Excel {EXCEL_MAX_COLS}). "
            f"Separador provavelmente errado. Ajuste CSV_SEP."
        )

    df.to_excel(saida, index=False, engine="openpyxl")
    print(f"OK: {csv_file} -> {saida} ({len(df)} linhas, {df.shape[1]} colunas)")
    return str(saida)


def main():
    converter(CSV_INPUT_FILE, CSV_OUTPUT_FILE, CSV_SEP)


if __name__ == "__main__":
    main()
