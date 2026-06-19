import os

from pymongo import MongoClient, UpdateOne
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import islice

MONGO_CONN = os.getenv("PRD_MONGO_SA_EAST") 
DATABASE = "testeMigracao"
COLLECTION = "MetaGM"

client = MongoClient(MONGO_CONN, maxPoolSize=100)

collection = client[DATABASE][COLLECTION]

BATCH_SIZE = 1000
MAX_WORKERS = 10

def chunks(iterator, size):
    while True:
        batch = list(islice(iterator, size))
        if not batch:
            break
        yield batch

def process_batch(docs):

    operations = []

    for doc in docs:

        details = doc.get("details")
        modified = False

        if isinstance(details, list):

            for item in details:
                if isinstance(item, dict) and "TemplateId" in item:
                    del item["TemplateId"]
                    modified = True

        elif isinstance(details, dict):

            if "TemplateId" in details:
                del details["TemplateId"]
                modified = True

        if modified:
            operations.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {"$set": {"details": details}}
                )
            )

    if operations:
        result = collection.bulk_write(
            operations,
            ordered=False
        )
        return result.modified_count

    return 0

cursor = collection.find(
    {"details.TemplateId": {"$exists": True}},
    no_cursor_timeout=True
)

total_updated = 0

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

    futures = [
        executor.submit(process_batch, batch)
        for batch in chunks(cursor, BATCH_SIZE)
    ]

    for future in as_completed(futures):
        total_updated += future.result()
        print(f"Atualizados até agora: {total_updated}")

cursor.close()

print(f"\nTotal atualizado: {total_updated}")
