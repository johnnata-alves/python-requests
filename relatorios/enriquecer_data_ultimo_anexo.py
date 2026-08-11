import os
import sys
import pandas as pd
from pymongo import MongoClient, DESCENDING
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DATABASE = "ClaimEngine"

PLANILHA = sys.argv[1] if len(sys.argv) > 1 else "planilha.xlsx"


def main():
    client = MongoClient(MONGO_URI)
    db = client[DATABASE]

    df = pd.read_excel(PLANILHA)

    if "cd_sinistro" not in df.columns:
        print("ERRO: coluna 'cd_sinistro' não encontrada na planilha.")
        return

    datas = []

    for i, row in df.iterrows():
        sinistro = row["cd_sinistro"]
        data_anexo = None

        try:
            claim = db.LegacyClaim.find_one(
                {"claimNumber": int(sinistro)},
                {"protocol": 1}
            )

            if claim and claim.get("protocol"):
                protocol = claim["protocol"]

                attachment = db.LegacyAttachment.find_one(
                    {"protocol": protocol},
                    {"createdAt": 1},
                    sort=[("createdAt", DESCENDING)]
                )

                if attachment and attachment.get("createdAt"):
                    data_anexo = attachment["createdAt"]

        except Exception as e:
            print(f"Erro no sinistro {sinistro}: {e}")

        datas.append(data_anexo)

        if (i + 1) % 50 == 0:
            print(f"Processados: {i + 1}/{len(df)}")

    col_idx = df.columns.get_loc("cd_sinistro") + 1
    df.insert(col_idx, "Data Ultimo Anexo", datas)

    df.to_excel(PLANILHA, index=False, engine="openpyxl")
    print(f"\nFinalizado. Planilha salva: {PLANILHA}")
    print(f"Total: {len(df)} | Com data: {sum(1 for d in datas if d is not None)}")

    client.close()


if __name__ == "__main__":
    main()
