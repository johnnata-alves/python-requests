import os
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("HML_MONGO_URI"))

db = client["ProductEngine"]
collection = db["productClaim"]

filter_query = {
    "erpProductIds": {
        "$in": [
            365, 132, 225, 274, 119, 246, 249, 215, 360, 251,
            397, 226, 258, 357, 98, 171, 299, 100, 164, 203,
            312, 319, 97, 214, 390, 234, 52, 286, 313, 213,
            53, 259, 320, 101, 287, 104, 235, 344, 102, 300,
            181, 211, 391, 125, 123, 124, 282, 122
        ]
    },
    "coverages.documentation.isActive": True
}

documents = collection.find(filter_query)

rows = []

for doc in documents:

    coverages = doc.get("coverages", [])

    for coverage in coverages:

        coverage_name = coverage.get("coverageName")
        cause_type = coverage.get("causeType")
        product = coverage.get("product")
        coverage_group_id = coverage.get("coverageGroupId")

        documentations = coverage.get("documentation", [])

        for documentation in documentations:

            if documentation.get("isActive") is True:

                documentation_type = documentation.get("type")

                rows.append({
                    "coverageName": coverage_name,
                    "causeType": cause_type,
                    "product": product,
                    "coverageGroupId": coverage_group_id,
                    "documentationType": documentation_type
                })

df = pd.DataFrame(rows)

total_antes = len(df)
df = df.drop_duplicates().reset_index(drop=True)
total_depois = len(df)

now = datetime.now().strftime("%Y%m%d_%H%M")
output_file = f"base_excel_{now}.xlsx"

df.to_excel(output_file, index=False, sheet_name="Resultado")

print(f"[OK] {total_depois} linhas exportadas para {output_file} "
      f"({total_antes - total_depois} duplicadas removidas)")
