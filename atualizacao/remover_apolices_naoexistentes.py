import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_CONNECTION = os.getenv("HML_MONGO_URI")

client = MongoClient(MONGO_CONNECTION)

db_claim = client["ClaimEngine"]
db_indexed = client["indexed_policy_too"]

notifications = db_claim.Notification.find(
    {"userCode": "johnnata.alves"},
    {"policyNumber": 1, "flowId": 1}
)

for doc in notifications:
    policy_number = str(doc.get("policyNumber"))
    flow_id = doc.get("flowId")

    person = db_indexed.person.find_one(
        {"policy_number": policy_number}
    )

    if not person:
        db_claim.Notification.delete_one({"_id": doc["_id"]})
        db_claim.Claim.delete_many({"flowId": flow_id})
        print(f"Removido policyNumber {policy_number} - flowId {flow_id}")

print("Processo finalizado.")
