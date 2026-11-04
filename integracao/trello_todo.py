"""Converte o JSON exportado de um quadro do Trello para o CSV de modelo do Todoist.

Mapeamento:
  lista do Trello       -> seção
  cartão                -> tarefa (descrição, data de entrega, etiquetas)
  item de checklist     -> subtarefa
  comentário            -> comentário da tarefa (com --comentarios)

Uso:
  TRELLO_JSON=quadro.json python trello_todo.py [saida.csv] [--comentarios] [--incluir-concluidos]

O arquivo de entrada vem da variável de ambiente TRELLO_JSON (ou do .env).
"""
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TRELLO_JSON = "personal.json"

COLUNAS = ["TYPE", "CONTENT", "DESCRIPTION", "PRIORITY", "INDENT", "AUTHOR",
           "RESPONSIBLE", "DATE", "DATE_LANG", "TIMEZONE"]


def linha(tipo, conteudo, indent=1, descricao="", data=""):
    return {"TYPE": tipo, "CONTENT": conteudo, "DESCRIPTION": descricao,
            "PRIORITY": 4 if tipo == "task" else "", "INDENT": indent,
            "AUTHOR": "", "RESPONSIBLE": "", "DATE": data,
            "DATE_LANG": "en" if data else "", "TIMEZONE": ""}


def nome_etiqueta(label):
    nome = (label.get("name") or label.get("color") or "").strip()
    return "@" + "_".join(nome.split()) if nome else ""


def converter_data(iso):
    if not iso:
        return ""
    # Trello grava em UTC; converte para o fuso local da máquina
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    return dt.strftime("%Y-%m-%d") if (dt.hour, dt.minute) == (0, 0) else dt.strftime("%Y-%m-%d %H:%M")


def converter(quadro, com_comentarios=False, incluir_concluidos=False):
    etiquetas = {l["id"]: nome_etiqueta(l) for l in quadro.get("labels", [])}

    checklists = {}
    for cl in quadro.get("checklists", []):
        checklists.setdefault(cl["idCard"], []).append(cl)

    comentarios = {}
    if com_comentarios:
        for a in quadro.get("actions", []):
            if a.get("type") == "commentCard":
                comentarios.setdefault(a["data"]["card"]["id"], []).append(a["data"]["text"])

    cartoes = {}
    for c in quadro.get("cards", []):
        if c.get("closed") or (c.get("dueComplete") and not incluir_concluidos):
            continue
        cartoes.setdefault(c["idList"], []).append(c)

    linhas = []
    listas = sorted((l for l in quadro.get("lists", []) if not l.get("closed")), key=lambda l: l["pos"])
    for lista in listas:
        linhas.append(linha("section", lista["name"]))
        for c in sorted(cartoes.get(lista["id"], []), key=lambda c: c["pos"]):
            tags = " ".join(filter(None, (etiquetas.get(i) for i in c.get("idLabels", []))))
            titulo = f"{c['name']} {tags}".strip()
            linhas.append(linha("task", titulo, 1, c.get("desc", ""), converter_data(c.get("due"))))

            # comentários antigos primeiro (o Trello exporta do mais novo pro mais velho)
            for texto in reversed(comentarios.get(c["id"], [])):
                linhas.append(linha("note", texto))

            for cl in sorted(checklists.get(c["id"], []), key=lambda cl: cl["pos"]):
                for item in sorted(cl.get("checkItems", []), key=lambda i: i["pos"]):
                    if item.get("state") == "complete" and not incluir_concluidos:
                        continue
                    linhas.append(linha("task", item["name"], 2, data=converter_data(item.get("due"))))
    return linhas


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not TRELLO_JSON:
        sys.exit(__doc__)
    entrada = Path(TRELLO_JSON)
    saida = Path(args[0]) if args else entrada.with_suffix(".csv")

    quadro = json.loads(entrada.read_text(encoding="utf-8"))
    linhas = converter(quadro, "--comentarios" in sys.argv, "--incluir-concluidos" in sys.argv)

    with saida.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        w.writerows(linhas)

    tarefas = sum(1 for l in linhas if l["TYPE"] == "task")
    print(f"{saida}: {tarefas} tarefas em {sum(1 for l in linhas if l['TYPE'] == 'section')} seções")
    if tarefas > 300:
        print("Aviso: o Todoist limita projetos a 300 tarefas ativas; divida o quadro em mais de um CSV.")


if __name__ == "__main__":
    main()
