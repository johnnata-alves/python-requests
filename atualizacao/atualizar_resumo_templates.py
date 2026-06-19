import os
import re
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("HML_MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["NotificationEngine"]
collection = db["templates"]

PROPRIEDADES_OBRIGATORIAS = [
    ("Nome do solicitante", "nomeSolicitante"),
    ("Nome social do solicitante", "nomeSocialSolicitante"),
    ("CPF do solicitante", "cpfSolicitante"),
    ("Nome do segurado", "nomeSegurado"),
    ("CPF do segurado", "cpfSegurado"),
    ("Protocolo", "protocolo"),
    ("Nome da cobertura", "nomeCobertura"),
    ("Data da comunicação", "dataComunicacao"),
    ("Acontecimento", "acontecimento"),
    ("Numero Apólice", "numeroApolice"),
    ("Nome Produto", "nomeProduto"),
    ("Email Reclamante", "emailReclamante"),
    ("Telefone Reclamante", "telefoneReclamante"),
]

def extrair_blocos(resumo):
    match = re.search(r"(Propriedades:\n)(.*?)((\nResumo:|\Z))", resumo, re.DOTALL)
    if not match:
        return None, None, None
    antes = resumo[:match.start(2)]
    propriedades_texto = match.group(2)
    depois = resumo[match.end(2):]
    return antes, propriedades_texto, depois

def verificar_e_atualizar():
    templates = collection.find({})
    total = 0
    atualizados = 0

    for template in templates:
        total += 1
        resumo = template.get("resumo_da_ocorrencia", "")
        if not resumo:
            continue

        antes, propriedades_texto, depois = extrair_blocos(resumo)
        if antes is None:
            continue

        linhas_existentes = [l for l in propriedades_texto.strip().split("\n") if l.startswith("- ")]

        propriedades_existentes_lower = set()
        for linha in linhas_existentes:
            match_var = re.search(r"\{\{(\w+)\}\}", linha)
            if match_var:
                propriedades_existentes_lower.add(match_var.group(1).lower())

        faltando = []
        for label, variavel in PROPRIEDADES_OBRIGATORIAS:
            if variavel.lower() not in propriedades_existentes_lower:
                faltando.append(f"- {label}: {{{{{variavel}}}}}")

        if not faltando:
            continue

        novas_propriedades = "\n".join(linhas_existentes + faltando)
        resumo_atualizado = antes + novas_propriedades + "\n\n" + depois.lstrip("\n")

        if not resumo_atualizado.rstrip().endswith(depois.strip()):
            resumo_atualizado = antes + novas_propriedades + "\n" + depois

        collection.update_one(
            {"_id": template["_id"]},
            {"$set": {"resumo_da_ocorrencia": resumo_atualizado}}
        )
        atualizados += 1
        print(f"[OK] {template.get('name', template['_id'])} - adicionadas {len(faltando)} propriedade(s)")

    print(f"\nFinalizado. Total: {total} | Atualizados: {atualizados}")
    client.close()

if __name__ == "__main__":
    verificar_e_atualizar()
