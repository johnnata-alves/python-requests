import os
from dotenv import load_dotenv
from pymongo import MongoClient, DESCENDING

load_dotenv()

client = MongoClient(os.getenv("PRD_MONGO_MONITORING"))
db = client["ClaimEngine"]

collectionA = db["Notification"]
collectionB = db["Timeline"]

records = collectionA.find({
    "$or": [
        { "UpdatedAt": { "$exists": False } },
        { "UpdatedAt": None }
    ]
})

for doc in records:
    flow_id = doc.get("flowId")

    if not flow_id:
        continue

    last_record = collectionB.find_one(
        { "flowId": flow_id },
        sort=[("CreatedAt", DESCENDING)]
    )

    if last_record and "CreatedAt" in last_record:
        updated_value = last_record["CreatedAt"]

        collectionA.update_one(
            { "_id": doc["_id"] },
            { "$set": { "UpdatedAt": updated_value } }
        )

        print(f"Atualizado flowId {flow_id} com UpdatedAt = {updated_value}")
    else:
        print(f"Nenhum registro encontrado na segunda collection para flowId {flow_id}")
