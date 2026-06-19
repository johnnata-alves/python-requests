import argparse
import os
from typing import Dict, List

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

searchCoverageIds: Dict[int, List[str]] = {
    182: "MIP",
    377: "MIP",
}

def main() -> None:
    parser = argparse.ArgumentParser(description="Atualiza coverageName nos registros.")
    parser.add_argument(
        "--uri",
        default=os.getenv("PRD_MONGO_SUBSCRICAO"),
    )
    parser.add_argument("--db", default=os.getenv("MONGO_DB", "ProductEngine"))
    parser.add_argument(
        "--collection", default=os.getenv("MONGO_COLLECTION", "productClaim")
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra as alterações encontradas sem gravar no banco.",
    )
    args = parser.parse_args()

    client = MongoClient(args.uri)
    collection = client[args.db][args.collection]

    updated_docs = 0
    updated_items = 0

    for doc in collection.find({}, {"coverages": 1}):
        coverages = doc.get("coverages") or []
        changed = False

        for coverage in coverages:
            coverageId = coverage.get("coverageId")
            if coverageId not in searchCoverageIds:
                continue

            coverage["coverageName"] = searchCoverageIds.get(coverageId)

            updated_items += 1
            changed = True

        if changed:
            updated_docs += 1
            if args.dry_run:
                print(f"[dry-run] Atualizaria _id={doc.get('_id')}")
            else:
                collection.update_one(
                    {"_id": doc["_id"]}, {"$set": {"coverages": coverages}}
                )

    print(
        f"Registros atualizados: {updated_docs} | "
        f"entradas documentation alteradas: {updated_items}"
    )

if __name__ == "__main__":
    main()
