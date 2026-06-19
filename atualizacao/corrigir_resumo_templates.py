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

def corrigir():
    templates = collection.find({})
    total = 0
    corrigidos = 0

    for template in templates:
        total += 1
        resumo = template.get("resumo_da_ocorrencia", "")
        if not resumo:
            continue

        match_resumo = re.search(r"\nResumo:\n", resumo)
        if not match_resumo:
            continue

        texto_apos_resumo = resumo[match_resumo.end():]
        linhas_soltas = re.findall(r"^- .+\{\{.+\}\}.*$", texto_apos_resumo, re.MULTILINE)

        if not linhas_soltas:
            continue

        texto_limpo_apos = texto_apos_resumo
        for linha in linhas_soltas:
            texto_limpo_apos = texto_limpo_apos.replace(linha + "\n", "")
            texto_limpo_apos = texto_limpo_apos.replace(linha, "")

        texto_limpo_apos = texto_limpo_apos.rstrip("\n")

        parte_antes_resumo = resumo[:match_resumo.start()]

        match_props = re.search(r"Propriedades:\n", parte_antes_resumo)
        if not match_props:
            continue

        bloco_props_inicio = match_props.end()
        bloco_props_fim = len(parte_antes_resumo)
        bloco_props = parte_antes_resumo[bloco_props_inicio:bloco_props_fim].rstrip("\n")

        linhas_props_existentes = [l for l in bloco_props.split("\n") if l.startswith("- ")]

        vars_existentes = set()
        for linha in linhas_props_existentes:
            m = re.search(r"\{\{(\w+)\}\}", linha)
            if m:
                vars_existentes.add(m.group(1).lower())

        novas_linhas = []
        for linha in linhas_soltas:
            m = re.search(r"\{\{(\w+)\}\}", linha)
            if m and m.group(1).lower() not in vars_existentes:
                novas_linhas.append(linha)
                vars_existentes.add(m.group(1).lower())

        for label, variavel in PROPRIEDADES_OBRIGATORIAS:
            if variavel.lower() not in vars_existentes:
                novas_linhas.append(f"- {label}: {{{{{variavel}}}}}")
                vars_existentes.add(variavel.lower())

        todas_props = linhas_props_existentes + novas_linhas
        bloco_final_props = "\n".join(todas_props)

        resumo_corrigido = (
            parte_antes_resumo[:bloco_props_inicio]
            + bloco_final_props
            + "\n\nResumo:\n"
            + texto_limpo_apos
        )

        collection.update_one(
            {"_id": template["_id"]},
            {"$set": {"resumo_da_ocorrencia": resumo_corrigido}}
        )
        corrigidos += 1
        print(f"[CORRIGIDO] {template.get('name', template['_id'])} - {len(linhas_soltas)} linha(s) movidas para Propriedades")

    print(f"\nFinalizado. Total: {total} | Corrigidos: {corrigidos}")
    client.close()

if __name__ == "__main__":
    corrigir()
