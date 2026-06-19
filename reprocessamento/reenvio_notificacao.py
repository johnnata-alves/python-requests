import os
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DB = "SinistrosMicroService"
COL = "SinistroTimeline"

sinistros = [
"2007700028168",
"2007700028082",
"2007700028851",
"2007700030084",
"2007700030073",
"2007700030303",
"2007700034117",
"2007700034137",
"2007700034148",
"2007700027662",
"2007700027476",
"2007700027726",
"2007700027401",
"2007700029465",
"2007700028037",
"2007700028301",
"2007700028828",
"2007700029506",
"2007700029375"
]

client = MongoClient(MONGO_URI)
col = client[DB][COL]

now = datetime.now(timezone.utc)

for s in sinistros:
    doc = col.find_one({"NumeroSinistro": s, "Codigo": "426"})
    if not doc:
        print("Não encontrado:", s)
        continue

    doc.pop("_id", None)
    doc["_id"] = str(uuid4())
    doc["DataEvento"] = now
    doc["DataInclusao"] = now
    doc["ParceiroNotificado"] = False

    col.insert_one(doc)
    print("Reinserido:", s)
