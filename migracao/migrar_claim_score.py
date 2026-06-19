import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_HML = os.getenv("HML_MONGO_URI")
MONGO_PRD = os.getenv("PRD_MONGO_URI")

DB_NAME = "ClaimEngine"

client_hml = MongoClient(MONGO_HML)
client_prd = MongoClient(MONGO_PRD)

db_hml = client_hml[DB_NAME]
db_prd = client_prd[DB_NAME]

col_notification_hml = db_hml["Notification"]
col_claim_score_prd = db_prd["ClaimScore"]
col_claim_score_hml = db_hml["ClaimScore"]

def remover_prefixo_9(flow_id):
    """Remove o '9' da frente do flowId. Ex: '9202600016866' -> '202600016866'"""
    s = str(flow_id)
    if s.startswith("9"):
        return s[1:]
    return s

def adicionar_prefixo_9(flow_id):
    """Adiciona '9' na frente do flowId. Ex: '202600016866' -> '9202600016866'"""
    s = str(flow_id)
    if not s.startswith("9"):
        return "9" + s
    return s

def main():
    filtro = {"userCode": "claim-migracao"}
    notifications = col_notification_hml.find(filtro, {"flowId": 1, "_id": 0})

    flow_ids = [n["flowId"] for n in notifications if n.get("flowId")]
    print(f"Total de flowIds encontrados na Notification HML: {len(flow_ids)}")

    inseridos = 0
    erros = 0

    for flow_id_hml in flow_ids:
        flow_id_prd = remover_prefixo_9(flow_id_hml)

        docs = list(col_claim_score_prd.find({"flowId": flow_id_prd}))

        if not docs:
            print(f"  [SKIP] flowId={flow_id_prd} não encontrado na ClaimScore PRD")
            erros += 1
            continue

        for doc in docs:
            doc.pop("_id", None)
            doc["flowId"] = adicionar_prefixo_9(doc.get("flowId", flow_id_prd))
            doc["status"] = "Pending"
            doc["newTimeline"] = False

            try:
                flow_hml = doc["flowId"]
                resultado = col_claim_score_hml.delete_many({"flowId": flow_hml})
                if resultado.deleted_count > 0:
                    print(f"  [DEL] flowId={flow_hml} removidos {resultado.deleted_count} registro(s) da ClaimScore HML")

                col_claim_score_hml.insert_one(doc)
                inseridos += 1
                print(f"  [OK] flowId={flow_hml} inserido na ClaimScore HML")
            except Exception as e:
                erros += 1
                print(f"  [ERRO] flowId={doc.get('flowId')}: {e}")

    print(f"\nFinalizado. Inseridos: {inseridos} | Erros/Skips: {erros}")

if __name__ == "__main__":
    main()
