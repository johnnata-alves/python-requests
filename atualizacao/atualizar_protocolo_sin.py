"""
Busca LegacyClaim com protocol "SIN-*" e produtos PAN,
tenta encontrar na AvisoSinistro por CPF + data ocorrência + cobertura,
e atualiza o protocolo na LegacyClaim se encontrar match.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

MONGO_URI_CLAIM = os.getenv("PRD_MONGO_URI")
MONGO_URI_SINISTRO = os.getenv("PRD_MONGO_SA_EAST")
DB_CLAIM = "ClaimEngine"
DB_SINISTRO = "SinistrosMicroService"
WORKERS = 20

PRODUTOS_PAN = [215, 246, 249, 251, 260, 272, 274, 363, 365, 372, 389]

lock = threading.Lock()
totais = {"atualizado": 0, "nao_encontrado": 0, "erro": 0}


def carregar_cobertura_config():
    """Carrega CoberturaConfiguracao para montar mapa de cobertura."""
    client = MongoClient(MONGO_URI_SINISTRO)
    db = client[DB_SINISTRO]

    config_map = []
    for cfg in db["CoberturaConfiguracao"].find():
        grupo_ids = set()
        cobertura_ids = set()

        # CoberturasIntegracao
        for ci in cfg.get("CoberturasIntegracao") or []:
            gci = ci.get("GrupoCoberturaId")
            cid = ci.get("CoberturaId")
            if gci is not None:
                grupo_ids.add(gci)
            if cid is not None:
                cobertura_ids.add(cid)

        # CoberturaId raiz
        cob_id = cfg.get("CoberturaId")
        if cob_id is not None:
            cobertura_ids.add(cob_id)

        config_map.append({
            "grupo_ids": grupo_ids,
            "cobertura_ids": cobertura_ids,
            "coverage_claim_engine": cfg.get("CoverageClaimEngine"),
        })

    client.close()
    return config_map


def match_cobertura(aviso_coberturas, legacy_coverages, config_map):
    """Verifica se há match de cobertura entre AvisoSinistro e LegacyClaim."""
    # IDs da LegacyClaim
    legacy_grupo_ids = set()
    for cov in legacy_coverages or []:
        gc = cov.get("groupCoverageCode")
        if gc is not None:
            legacy_grupo_ids.add(gc)

    # IDs do AvisoSinistro
    aviso_grupo_ids = set()
    aviso_cob_ids = set()
    for cob in aviso_coberturas or []:
        gci = cob.get("GrupoCoberturaId")
        cid = cob.get("_id")
        if gci is not None:
            aviso_grupo_ids.add(gci)
        if cid is not None:
            aviso_cob_ids.add(cid)

    # Cruzar via CoberturaConfiguracao
    for cfg in config_map:
        # Checa se aviso bate com algum config
        aviso_match = (
            aviso_grupo_ids & cfg["grupo_ids"] or
            aviso_cob_ids & cfg["cobertura_ids"]
        )
        # Checa se legacy bate com algum config
        legacy_match = legacy_grupo_ids & cfg["grupo_ids"]

        if aviso_match and legacy_match:
            return True

    # Match direto sem config
    if aviso_grupo_ids & legacy_grupo_ids:
        return True

    return False


def processar_claim(claim, config_map):
    client_sinistro = MongoClient(MONGO_URI_SINISTRO)
    client_claim = MongoClient(MONGO_URI_CLAIM)
    db_sinistro = client_sinistro[DB_SINISTRO]
    db_claim = client_claim[DB_CLAIM]

    claim_id = claim["_id"]
    cpf = (claim.get("insured") or {}).get("documentNumber", "")
    occurrence_date = claim.get("occurrenceDate")
    legacy_coverages = claim.get("coverages") or []
    claim_number = claim.get("claimNumber")

    try:
        if not cpf:
            with lock:
                totais["nao_encontrado"] += 1
            return

        # Buscar AvisoSinistro por CPF
        filtro_aviso = {"Segurado.CpfCnpj": cpf}
        avisos = list(db_sinistro["AvisoSinistro"].find(filtro_aviso))

        if not avisos:
            with lock:
                totais["nao_encontrado"] += 1
            return

        # 1. Prioridade: encontrar pelo array Sinistros (claimNumber)
        encontrado = None
        str_claim = str(claim_number)
        for aviso in avisos:
            sinistros_arr = aviso.get("Sinistros") or []
            if str_claim in sinistros_arr:
                encontrado = aviso
                break

        # 2. Fallback: filtrar por data de ocorrência + cobertura
        if not encontrado:
            for aviso in avisos:
                aviso_ocorrencia = aviso.get("Ocorrencia")
                if not aviso_ocorrencia or not occurrence_date:
                    continue

                diff = abs((aviso_ocorrencia - occurrence_date).days)
                if diff > 2:
                    continue

                aviso_coberturas = aviso.get("Coberturas") or []
                if match_cobertura(aviso_coberturas, legacy_coverages, config_map):
                    encontrado = aviso
                    break

        if not encontrado:
            with lock:
                totais["nao_encontrado"] += 1
            return

        # Atualizar protocolo na LegacyClaim
        novo_protocolo = encontrado.get("Protocolo")
        if not novo_protocolo:
            with lock:
                totais["nao_encontrado"] += 1
            return

        db_claim["LegacyClaim"].update_one(
            {"_id": claim_id},
            {"$set": {"protocol": novo_protocolo}}
        )

        with lock:
            totais["atualizado"] += 1

    except Exception as e:
        with lock:
            totais["erro"] += 1

    finally:
        client_sinistro.close()
        client_claim.close()


def main():
    print("Carregando CoberturaConfiguracao...")
    config_map = carregar_cobertura_config()
    print(f"  Configs carregadas: {len(config_map)}")

    client = MongoClient(MONGO_URI_CLAIM)
    db = client[DB_CLAIM]

    print("Buscando LegacyClaim com protocol SIN-* e produtos PAN...")
    filtro = {
        "product": {"$in": PRODUTOS_PAN},
        "protocol": {"$regex": "^SIN-", "$options": "i"},
        "claimNumber": 2007700038708
    }

    claims = list(db["LegacyClaim"].find(filtro))
    client.close()

    print(f"Total LegacyClaim encontradas: {len(claims)}")

    if not claims:
        print("Nada para processar.")
        return

    with tqdm(total=len(claims), desc="Buscando protocolo", unit="doc") as pbar:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {
                executor.submit(processar_claim, c, config_map): c
                for c in claims
            }
            for future in as_completed(futures):
                future.result()
                pbar.update(1)

    print(f"\nFinalizado!")
    print(f"  Total: {len(claims)}")
    print(f"  Atualizados: {totais['atualizado']}")
    print(f"  Não encontrado: {totais['nao_encontrado']}")
    print(f"  Erros: {totais['erro']}")


if __name__ == "__main__":
    main()
