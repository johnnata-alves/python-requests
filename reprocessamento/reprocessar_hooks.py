import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

load_dotenv()

clientEmissao = MongoClient(os.getenv("PRD_MONGO_EMISSAO"))
clientIssuance = MongoClient(os.getenv("PRD_MONGO_INSURANCE_PLATFORM"))

dbEmissao = clientEmissao["Pippin"]
dbIssuance = clientIssuance["OrchestratorIssuance"]
dbMonitoring = clientIssuance["Monitoring"]
issuance_collection = dbEmissao["Issuance"]
flows_collection = dbIssuance["flows"]
monitoring_collection = dbMonitoring["Proposal"]
proposals = monitoring_collection.find({"parceiro_notificado": "Não", "status_emissao": "ISSUED"})

for proposal in proposals:
    flow_id = proposal.get("flowId")
    if flow_id:
        issuance_collection.update_one(
            {"source.correlation_id": flow_id},
            {"$set": {"status": "WAITING_ERP"}}
        )

        flows_collection.update_one(
            {"_id": ObjectId(flow_id)},
            {
                "$unset": {"payloads.issuance_accepted": ""},
                "$set": {"current_step": "issuance_accepted", "status": "pending"}
            }
        )
print("Automação concluída.")
