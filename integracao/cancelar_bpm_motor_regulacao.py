import os
import xml.etree.ElementTree as ET
from datetime import datetime

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_AVISO_CONNECTION = os.getenv("PRD_MONGO_SA_EAST")
DATABASE_AVISO = "SinistrosMicroService"
BPM_BASE_URL = os.getenv("BPM_BASE_URL", "http://toovasp019/BPMTOO")
DATA_CORTE = datetime(2026, 6, 20)


def consultar_caso(nr_sinistro):
    url = f"{BPM_BASE_URL}/WebServices/QuerySOA.asmx"
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/QueryCasesAsString"
    }
    data = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <QueryCasesAsString xmlns="http://tempuri.org/">
      <sxml><![CDATA[
        <BizAgiWSParam>
          <Domain>domain</Domain>
          <UserName>admon</UserName>
          <QueryParams>
            <XPaths>
              <XPath Path="TratamentoDeSinistros.Sinistro.NUMSinistro" Include="false" Approx="false">{nr_sinistro}</XPath>
            </XPaths>
          </QueryParams>
          <Parameters>
            <Parameter Name="nameEnt">TratamentoDeSinistros</Parameter>
            <Parameter Name="page">1</Parameter>
            <Parameter Name="pageSize">100</Parameter>
          </Parameters>
        </BizAgiWSParam>
      ]]></sxml>
    </QueryCasesAsString>
  </soap:Body>
</soap:Envelope>"""

    try:
        response = requests.post(url, headers=headers, data=data, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        ns = {
            "soap": "http://schemas.xmlsoap.org/soap/envelope/",
            "tempuri": "http://tempuri.org/"
        }
        result = root.find(".//tempuri:QueryCasesAsStringResult", namespaces=ns)
        if result is not None and result.text:
            bizagi = ET.fromstring(result.text)
            rows = bizagi.find(".//Rows")
            if rows is not None:
                for row in rows.findall("Row"):
                    radnumber = row.find("./Column[@Name='RADNUMBER']")
                    idcasestate = row.find("./Column[@Name='IDCASESTATE']")
                    if radnumber is not None and idcasestate is not None:
                        return {"caso_id": radnumber.text, "caso_status": idcasestate.text}
    except Exception as e:
        return {"error": str(e)}
    return None


def abortar_bpm(caso_id, nr_sinistro):
    url = f"{BPM_BASE_URL}/webservices/workflowenginesoa.asmx"
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://tempuri.org/abortCasesAsString",
    }
    data = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:xsd="http://www.w3.org/2001/XMLSchema"
               xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <abortCasesAsString xmlns="http://tempuri.org/">
      <info><![CDATA[
        <BizAgiWSParam>
          <domain>domain</domain>
          <userName>admon</userName>
          <cases>
            <case>
              <idCase>{caso_id}</idCase>
              <abortReason>Tratado pelo motor.</abortReason>
            </case>
          </cases>
        </BizAgiWSParam>
      ]]></info>
    </abortCasesAsString>
  </soap:Body>
</soap:Envelope>"""

    response = requests.post(url, headers=headers, data=data, timeout=30)
    return response.status_code == 200


def main():
    inicio = datetime.now()

    client = MongoClient(MONGO_AVISO_CONNECTION)
    db = client[DATABASE_AVISO]
    collection = db["AvisoSinistroAutomacao"]

    filtro = {
        "Processamento": {"$gt": DATA_CORTE},
        "Status": {"$regex": ".*Motor de Regulação.*", "$options": "i"},
    }

    registros = list(collection.find(filtro, {"Sinistro": 1}))
    total = len(registros)
    print(f"Registros encontrados: {total}")

    sucesso = 0
    erro = 0
    sem_caso = 0

    for idx, doc in enumerate(registros, 1):
        sinistro = doc.get("Sinistro")
        if not sinistro:
            erro += 1
            print(f"[{idx}/{total}] Sinistro vazio, pulando")
            continue

        caso = consultar_caso(sinistro)

        if caso is None or "error" in caso:
            msg = caso.get("error") if caso else "sem retorno"
            print(f"[{idx}/{total}] Sinistro {sinistro}: erro consulta - {msg}")
            erro += 1
            continue

        if caso.get("caso_status") != "5":
            print(f"[{idx}/{total}] Sinistro {sinistro}: status={caso.get('caso_status')} (não é 5), sem caso para cancelar")
            sem_caso += 1
            continue

        caso_id = caso["caso_id"]
        ok = abortar_bpm(caso_id, sinistro)
        if ok:
            print(f"[{idx}/{total}] Sinistro {sinistro}: caso {caso_id} abortado")
            sucesso += 1
        else:
            print(f"[{idx}/{total}] Sinistro {sinistro}: FALHA ao abortar caso {caso_id}")
            erro += 1

    client.close()

    duracao = (datetime.now() - inicio).total_seconds()
    print("\n" + "=" * 60)
    print("CANCELAMENTO BPM - MOTOR DE REGULAÇÃO")
    print("=" * 60)
    print(f"Total: {total}")
    print(f"Sucesso (abortados): {sucesso}")
    print(f"Sem caso status=5: {sem_caso}")
    print(f"Erros: {erro}")
    print(f"Duração: {duracao:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
