import os
import json
import time
import html as html_module
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone

import requests
import urllib3
from dotenv import load_dotenv
from pymongo import MongoClient
from requests.exceptions import SSLError as RequestsSSLError

load_dotenv()
warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MONGO_URI = os.getenv("PRD_MONGO_URI")
DB_NAME = "ClaimEngine"
COLLECTION = "Attachment"
FILTER_DATE = datetime(2026, 5, 12, 0, 0, 0, tzinfo=timezone.utc)

COPILOT_API_KEY = os.getenv("COPILOT_API_KEY")
COPILOT_MODEL = os.getenv("COPILOT_MODEL", "gpt-5.1-mini")
DIRECT_LINE_BASE_URL = os.getenv("DIRECT_LINE_BASE_URL", "https://directline.botframework.com/v3/directline")
DIRECT_LINE_SSL_VERIFY = os.getenv("DIRECT_LINE_SSL_VERIFY", "true").strip().lower() not in ["0", "false", "no", "off"]
CLIENT_AI_USER_ID = "analise-attachments"
POLL_ATTEMPTS = 60
POLL_INTERVAL_SECONDS = 2

DASHBOARDS_DIR = "dashboards"
os.makedirs(DASHBOARDS_DIR, exist_ok=True)

class CopilotClient:
    def __init__(self):
        self.api_key = COPILOT_API_KEY
        self.base_url = DIRECT_LINE_BASE_URL.rstrip("/")
        self.verify_ssl = DIRECT_LINE_SSL_VERIFY

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _request(self, method, url, **kwargs):
        try:
            return requests.request(method, url, verify=self.verify_ssl, **kwargs)
        except RequestsSSLError as error:
            raise RuntimeError("Falha SSL ao chamar Direct Line.") from error

    def ask(self, prompt):
        start_response = self._request(
            "POST", f"{self.base_url}/conversations",
            headers=self._headers(), timeout=30
        )
        start_response.raise_for_status()
        conversation_id = start_response.json().get("conversationId")

        activity_payload = {
            "type": "message",
            "text": prompt,
            "from": {"id": CLIENT_AI_USER_ID},
            "channelData": {"model": COPILOT_MODEL}
        }

        post_response = self._request(
            "POST", f"{self.base_url}/conversations/{conversation_id}/activities",
            headers=self._headers(), json=activity_payload, timeout=30
        )
        post_response.raise_for_status()

        watermark = None
        for _ in range(POLL_ATTEMPTS):
            params = {"watermark": watermark} if watermark else None
            activities_response = self._request(
                "GET", f"{self.base_url}/conversations/{conversation_id}/activities",
                headers=self._headers(), params=params, timeout=30
            )
            activities_response.raise_for_status()
            payload = activities_response.json()
            watermark = payload.get("watermark")

            messages = [
                a.get("text") for a in (payload.get("activities") or [])
                if a.get("type", "").lower() == "message"
                and a.get("text")
                and (a.get("from") or {}).get("id", "").lower() != CLIENT_AI_USER_ID.lower()
            ]
            if messages:
                return messages[-1]

            time.sleep(POLL_INTERVAL_SECONDS)

        raise TimeoutError("Copilot nao retornou resposta.")

def coletar_dados():
    client = MongoClient(MONGO_URI)
    collection = client[DB_NAME][COLLECTION]
    docs = list(collection.find({"CreatedAt": {"$gte": FILTER_DATE}}))
    client.close()
    return docs

def gerar_resumo_estatistico(docs):
    total = len(docs)
    status_counter = Counter()
    doc_type_counter = Counter()
    sucesso_por_tipo = Counter()
    falha_por_tipo = Counter()
    erros_tipificacao = Counter()
    metadados_ausentes = Counter()
    metadados_invalidos = Counter()
    metadados_adicionais = defaultdict(Counter)
    problemas_por_tipo = defaultdict(list)

    for doc in docs:
        status = doc.get("status", "Unknown")
        status_counter[status] += 1

        validation_success = doc.get("metadataValidationSuccess", False)
        technical = doc.get("technicalDetails") or {}
        error_msg = technical.get("Error", "")

        doc_type_names = doc.get("documentTypeNames") or []
        doc_type = doc_type_names[0] if doc_type_names else "Não identificado"
        doc_type_counter[doc_type] += 1

        if validation_success:
            sucesso_por_tipo[doc_type] += 1
        else:
            falha_por_tipo[doc_type] += 1

        if status == "Failed" and error_msg:
            erros_tipificacao[error_msg] += 1

        if error_msg and "ausentes" in error_msg.lower():
            partes = error_msg.split("ausentes›")
            if len(partes) > 1:
                campos = [c.strip() for c in partes[1].split(",")]
                for campo in campos:
                    if campo:
                        metadados_ausentes[f"{doc_type} | {campo}"] += 1

        if error_msg and "inválidos" in error_msg.lower():
            partes = error_msg.split("inválidos›")
            if len(partes) > 1:
                campos = [c.strip() for c in partes[1].split(",")]
                for campo in campos:
                    if campo:
                        metadados_invalidos[f"{doc_type} | {campo}"] += 1

        metadata_list = doc.get("metadata") or []
        for meta in metadata_list:
            meta_doc_type = meta.get("DocumentType", doc_type)
            for field in meta.get("Fields", []):
                if field.get("Type") == "Additional":
                    key = field.get("Key", "")
                    metadados_adicionais[meta_doc_type][key] += 1

        if not validation_success and status != "Failed":
            problemas = []
            for meta in metadata_list:
                for field in meta.get("Fields", []):
                    if field.get("Type") != "Required":
                        continue
                    value = field.get("Value")
                    valid = field.get("Valid")
                    if value in [None, ""]:
                        problemas.append(f"ausente: {field.get('Key')}")
                    elif valid is False:
                        problemas.append(f"invalido: {field.get('Key')}")
            if problemas:
                problemas_por_tipo[doc_type].extend(problemas)

    problemas_freq = {}
    for tipo, lista in problemas_por_tipo.items():
        problemas_freq[tipo] = dict(Counter(lista).most_common(20))

    return {
        "total_documentos": total,
        "por_status": dict(status_counter.most_common()),
        "total_sucesso_validacao": sum(sucesso_por_tipo.values()),
        "total_falha_validacao": sum(falha_por_tipo.values()),
        "pct_sucesso": round(sum(sucesso_por_tipo.values()) / total * 100, 2) if total > 0 else 0,
        "por_tipo_documento": dict(doc_type_counter.most_common()),
        "sucesso_por_tipo": dict(sucesso_por_tipo.most_common()),
        "falha_por_tipo": dict(falha_por_tipo.most_common()),
        "top_erros_tipificacao": dict(erros_tipificacao.most_common(20)),
        "top_metadados_ausentes": dict(metadados_ausentes.most_common(30)),
        "top_metadados_invalidos": dict(metadados_invalidos.most_common(30)),
        "metadados_adicionais_por_tipo": {k: dict(v.most_common(10)) for k, v in metadados_adicionais.items()},
        "problemas_frequentes_por_tipo": problemas_freq,
    }

def enviar_para_ia(resumo):
    prompt = f"""Você é um analista de dados especialista em processamento de documentos e OCR.

Analise os dados estatísticos abaixo de anexos processados pelo sistema de tipificação de documentos.
Os dados representam o período a partir de 12/05/2026.

DADOS:
{json.dumps(resumo, ensure_ascii=False, indent=2)}

Com base nesses dados, me forneça uma análise completa e detalhada contendo:

1. PRINCIPAIS MOTIVOS DE FALHA
- Quais são os erros mais frequentes e suas causas raiz
- Separar entre falhas de tipificação (status=Failed) e falhas de validação de metadados

2. TAXA DE SUCESSO
- Quantidade total processada vs com sucesso (metadataValidationSuccess=true)
- Percentual geral e por tipo de documento

3. DETALHAMENTO POR TIPO DE DOCUMENTO
- Para cada tipo, quais são todos os problemas encontrados
- Frequência de cada problema (metadados ausentes e inválidos)
- Quais tipos têm pior desempenho e por quê

4. METADADOS ADICIONAIS
- Quais metadados adicionais estão sendo extraídos
- Quais deles poderiam ser correlacionados com campos Required ou Optional que estão faltando
- Sugestões de mapeamento Additional → Required para aumentar o preenchimento

5. PLANO DE AÇÃO PARA MELHORIAS
- Ações priorizadas por impacto (o que vai aumentar mais o % de OK)
- Quick wins vs melhorias estruturais
- Estimativa de impacto de cada ação no percentual de sucesso

6. OUTRAS ANÁLISES IMPORTANTES
- Padrões identificados
- Anomalias
- Recomendações técnicas específicas

Responda de forma estruturada, com números concretos e priorização clara."""

    client = CopilotClient()
    max_retries = 5
    invalid_responses = [
        "This agent is currently unavailable. It has reached its usage limit. Please try again later."
    ]

    for tentativa in range(1, max_retries + 1):
        print(f"  Tentativa {tentativa}/{max_retries}...")
        try:
            resposta = client.ask(prompt)
            if resposta and resposta.strip() not in invalid_responses:
                return resposta
        except (TimeoutError, RuntimeError) as e:
            print(f"  [ERRO] {e}")

        if tentativa < max_retries:
            print("  Aguardando 30s...")
            time.sleep(30)

    return None

def markdown_to_html(text):
    lines = text.split("\n")
    html_lines = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<h4 class="ai-h3">{html_module.escape(stripped[4:])}</h4>')
        elif stripped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<h3 class="ai-h2">{html_module.escape(stripped[3:])}</h3>')
        elif stripped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<h2 class="ai-h1">{html_module.escape(stripped[2:])}</h2>')
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = stripped[2:]
            content = content.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
            html_lines.append(f"<li>{content}</li>")
        elif stripped.startswith("|"):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f'<p class="ai-table-row">{html_module.escape(stripped)}</p>')
        elif stripped == "":
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<br>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            content = stripped
            while "**" in content:
                content = content.replace("**", "<strong>", 1).replace("**", "</strong>", 1)
            html_lines.append(f"<p>{content}</p>")

    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)

def gerar_html(resumo, analise_ia):
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    total = resumo["total_documentos"]
    sucesso = resumo["total_sucesso_validacao"]
    falha = resumo["total_falha_validacao"]
    pct = resumo["pct_sucesso"]

    status_json = json.dumps([{"s": k, "v": v} for k, v in resumo["por_status"].items()])
    tipos_json = json.dumps([
        {"t": k, "ok": resumo["sucesso_por_tipo"].get(k, 0), "nok": v - resumo["sucesso_por_tipo"].get(k, 0)}
        for k, v in list(resumo["por_tipo_documento"].items())[:20]
    ], ensure_ascii=False)

    ausentes_json = json.dumps([{"k": k, "v": v} for k, v in list(resumo["top_metadados_ausentes"].items())[:15]], ensure_ascii=False)
    invalidos_json = json.dumps([{"k": k, "v": v} for k, v in list(resumo["top_metadados_invalidos"].items())[:15]], ensure_ascii=False)

    analise_html = markdown_to_html(analise_ia) if analise_ia else '<p class="no-data">Análise da IA não disponível nesta execução.</p>'
    analise_html = analise_html.replace("✅ Quer que eu gere um dashboard visual (gráficos de barras e heatmap) com essas análises e previsões de impacto em formato pronto para apresentação executiva (Power BI style)?", "")
    analise_html = analise_html.replace("✅ Quer que eu genere um dashboard visual com gráficos (taxas, top erros, heatmap por tipo) e um plano de ação priorizado em formato Excel para você apresentar ao time?", "")

    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Report Executivo - Attachments | {now_str}</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{
    --primary: #00a3b3;
    --primary-light: #33c4d1;
    --primary-dark: #007a87;
    --primary-muted: #4dbdc8;
    --bg-dark: #1a2332;
    --bg-card: #1f2b3d;
    --bg-card-alt: #253447;
    --border: rgba(0, 163, 179, 0.2);
    --border-glow: rgba(0, 163, 179, 0.4);
    --text: #e8edf3;
    --text-muted: #8fa3b8;
    --text-dim: #5a7088;
    --success: #00c9a7;
    --danger: #ff5c7a;
    --warning: #00a3b3;
    --gradient-primary: linear-gradient(135deg, #00a3b3, #33c4d1);
    --gradient-card: linear-gradient(145deg, #253447, #1f2b3d);
    --gradient-accent: linear-gradient(135deg, #00a3b3, #0077b3);
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: 'Poppins', sans-serif;
    background: var(--bg-dark);
    color: var(--text);
    padding: 0;
    line-height: 1.7;
    min-height: 100vh;
}}
.container {{ max-width: 1400px; margin: 0 auto; padding: 40px 30px; }}

.header {{
    text-align: center;
    padding: 50px 0 40px;
    position: relative;
}}
.header::before {{
    content: '';
    position: absolute;
    top: 0; left: 50%;
    transform: translateX(-50%);
    width: 200px; height: 3px;
    background: var(--gradient-primary);
    border-radius: 2px;
}}
.header h1 {{
    font-size: 32px;
    font-weight: 700;
    background: var(--gradient-primary);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.5px;
}}
.header .subtitle {{
    color: var(--text-muted);
    font-size: 14px;
    font-weight: 300;
    margin-top: 10px;
}}
.header .badge {{
    display: inline-block;
    background: rgba(0, 163, 179, 0.1);
    border: 1px solid var(--border);
    color: var(--primary);
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 500;
    margin-top: 12px;
}}

.kpis {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin: 30px 0 40px;
}}
.kpi {{
    background: var(--gradient-card);
    border-radius: 16px;
    padding: 24px 20px;
    text-align: center;
    border: 1px solid var(--border);
    position: relative;
    overflow: hidden;
    transition: transform 0.2s, box-shadow 0.2s;
}}
.kpi:hover {{
    transform: translateY(-2px);
    box-shadow: 0 8px 30px rgba(0, 163, 179, 0.15);
}}
.kpi::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: var(--gradient-primary);
    opacity: 0.6;
}}
.kpi .value {{
    font-size: 36px;
    font-weight: 700;
    color: var(--primary-light);
    letter-spacing: -1px;
}}
.kpi .label {{
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 6px;
    font-weight: 400;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.kpi.danger .value {{ color: var(--danger); }}
.kpi.danger::before {{ background: linear-gradient(135deg, #ff4d6a, #ff6b8a); }}
.kpi.success .value {{ color: var(--success); }}
.kpi.success::before {{ background: linear-gradient(135deg, #00e6a0, #00ffb8); }}

.charts {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
    gap: 20px;
    margin: 30px 0;
}}
.chart-card {{
    background: var(--gradient-card);
    border-radius: 16px;
    padding: 24px;
    border: 1px solid var(--border);
    transition: box-shadow 0.2s;
}}
.chart-card:hover {{ box-shadow: 0 4px 20px rgba(0, 163, 179, 0.1); }}
.chart-card h3 {{
    color: var(--primary);
    margin-bottom: 16px;
    font-size: 14px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.chart-card canvas {{ max-height: 320px; }}
.full-width {{ grid-column: 1 / -1; }}

.section {{
    margin: 50px 0;
}}
.section h2 {{
    color: var(--text);
    font-size: 22px;
    font-weight: 600;
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 2px solid var(--border);
    display: flex;
    align-items: center;
    gap: 10px;
}}
.section h2 .icon {{
    font-size: 24px;
}}

.ai-section {{
    background: var(--gradient-card);
    border-radius: 16px;
    padding: 36px;
    border: 1px solid var(--border);
    position: relative;
}}
.ai-section::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: var(--gradient-accent);
    border-radius: 16px 16px 0 0;
}}
.ai-section h2 {{ color: var(--primary); font-size: 20px; margin: 28px 0 12px; font-weight: 600; }}
.ai-section h3 {{ color: var(--primary-light); font-size: 16px; margin: 22px 0 10px; font-weight: 600; }}
.ai-section h4 {{ color: var(--warning); font-size: 14px; margin: 16px 0 8px; font-weight: 500; }}
.ai-section p {{ color: var(--text); margin: 8px 0; font-size: 14px; font-weight: 300; }}
.ai-section ul {{ margin: 10px 0 10px 24px; }}
.ai-section li {{ color: rgba(232, 230, 240, 0.85); font-size: 13px; margin: 6px 0; font-weight: 300; }}
.ai-section strong {{ color: var(--primary-light); font-weight: 600; }}
.ai-h1 {{ color: var(--primary) !important; font-size: 22px !important; margin-top: 30px !important; }}
.ai-h2 {{ color: var(--primary-light) !important; font-size: 18px !important; }}
.ai-h3 {{ color: var(--warning) !important; font-size: 14px !important; }}
.no-data {{ color: var(--danger); font-style: italic; font-weight: 400; }}
.ai-table-row {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-muted); }}

.resumo-json {{
    background: rgba(26, 35, 50, 0.8);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-top: 16px;
    max-height: 400px;
    overflow-y: auto;
    display: none;
}}
.resumo-json.active {{ display: block; }}
.resumo-json pre {{
    color: var(--text-muted);
    font-size: 11px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    white-space: pre-wrap;
    line-height: 1.5;
}}
.toggle-btn {{
    background: var(--gradient-primary);
    border: none;
    color: #fff;
    padding: 10px 24px;
    border-radius: 8px;
    font-family: 'Poppins', sans-serif;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: opacity 0.2s, transform 0.2s;
}}
.toggle-btn:hover {{ opacity: 0.85; transform: translateY(-1px); }}

.footer {{
    text-align: center;
    padding: 40px 0 20px;
    color: var(--text-dim);
    font-size: 12px;
    font-weight: 300;
}}
</style>
</head>
<body>
<div class="container">

<div class="header">
<h1>Report Executivo de Attachments</h1>
<p class="subtitle">Análise de qualidade do processamento de documentos e metadados</p>
<span class="badge">Gerado em {now_str} &bull; Período: 12/05/2026 em diante</span>
</div>

<div class="kpis">
<div class="kpi"><div class="value">{total}</div><div class="label">Total Processados</div></div>
<div class="kpi success"><div class="value">{sucesso}</div><div class="label">Validação OK</div></div>
<div class="kpi danger"><div class="value">{falha}</div><div class="label">Não OK</div></div>
<div class="kpi"><div class="value">{pct}%</div><div class="label">Taxa de Sucesso</div></div>
<div class="kpi danger"><div class="value">{resumo['por_status'].get('Failed', 0)}</div><div class="label">Falha Total</div></div>
</div>

<div class="charts">
<div class="chart-card">
<h3>Taxa de Sucesso Global</h3>
<canvas id="chartPie"></canvas>
</div>
<div class="chart-card">
<h3>Distribuição por Status</h3>
<canvas id="chartStatus"></canvas>
</div>
<div class="chart-card full-width">
<h3>Top 20 Tipos de Documento &mdash; OK vs Não OK</h3>
<canvas id="chartTipos" height="120"></canvas>
</div>
<div class="chart-card full-width">
<h3>Top 15 Metadados Ausentes</h3>
<canvas id="chartAusentes" height="100"></canvas>
</div>
<div class="chart-card full-width">
<h3>Top 15 Metadados Inválidos</h3>
<canvas id="chartInvalidos" height="100"></canvas>
</div>
</div>

<div class="section">
<h2><span class="icon">🤖</span> Análise da IA &mdash; Plano de Ação</h2>
<div class="ai-section">
{analise_html}
</div>
</div>

<div class="section">
<h2><span class="icon">📦</span> Dados Brutos</h2>
<button class="toggle-btn" onclick="document.getElementById('jsonData').classList.toggle('active')">Mostrar / Ocultar JSON</button>
<div class="resumo-json" id="jsonData">
<pre>{html_module.escape(json.dumps(resumo, ensure_ascii=False, indent=2))}</pre>
</div>
</div>

<div class="footer">
ClaimEngine &bull; Report gerado automaticamente &bull; {now_str}
</div>

</div>

<script>
Chart.defaults.font.family = "'Poppins', sans-serif";
Chart.defaults.color = '#8b87a8';

const statusData = {status_json};
const tiposData = {tipos_json};
const ausentesData = {ausentes_json};
const invalidosData = {invalidos_json};

new Chart(document.getElementById('chartPie'), {{
    type: 'doughnut',
    data: {{
        labels: ['OK ({sucesso})', 'Não OK ({falha})'],
        datasets: [{{ data: [{sucesso}, {falha}], backgroundColor: ['#00c9a7', '#ff5c7a'], borderWidth: 0, borderRadius: 4 }}]
    }},
    options: {{
        cutout: '70%',
        plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#e8edf3', padding: 16, font: {{ size: 12 }} }} }} }}
    }}
}});

new Chart(document.getElementById('chartStatus'), {{
    type: 'bar',
    data: {{
        labels: statusData.map(d => d.s),
        datasets: [{{ data: statusData.map(d => d.v), backgroundColor: statusData.map(d => d.s === 'Typified' ? '#00a3b3' : d.s === 'Failed' ? '#ff5c7a' : '#4dbdc8'), borderRadius: 6 }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ grid: {{ display: false }} }}, y: {{ grid: {{ color: 'rgba(0,163,179,0.08)' }} }} }} }}
}});

new Chart(document.getElementById('chartTipos'), {{
    type: 'bar',
    data: {{
        labels: tiposData.map(d => d.t),
        datasets: [
            {{ label: 'OK', data: tiposData.map(d => d.ok), backgroundColor: '#00a3b3', borderRadius: 3 }},
            {{ label: 'Não OK', data: tiposData.map(d => d.nok), backgroundColor: '#ff5c7a', borderRadius: 3 }}
        ]
    }},
    options: {{
        indexAxis: 'y',
        plugins: {{ legend: {{ labels: {{ color: '#e8edf3' }} }} }},
        scales: {{ x: {{ stacked: true, grid: {{ color: 'rgba(0,163,179,0.06)' }} }}, y: {{ stacked: true, ticks: {{ font: {{ size: 10 }} }} }} }}
    }}
}});

new Chart(document.getElementById('chartAusentes'), {{
    type: 'bar',
    data: {{
        labels: ausentesData.map(d => d.k),
        datasets: [{{ data: ausentesData.map(d => d.v), backgroundColor: '#33c4d1', borderRadius: 4 }}]
    }},
    options: {{ indexAxis: 'y', plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ grid: {{ color: 'rgba(0,163,179,0.06)' }} }}, y: {{ ticks: {{ font: {{ size: 9 }} }} }} }} }}
}});

new Chart(document.getElementById('chartInvalidos'), {{
    type: 'bar',
    data: {{
        labels: invalidosData.map(d => d.k),
        datasets: [{{ data: invalidosData.map(d => d.v), backgroundColor: '#007a87', borderRadius: 4 }}]
    }},
    options: {{ indexAxis: 'y', plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ grid: {{ color: 'rgba(0,163,179,0.06)' }} }}, y: {{ ticks: {{ font: {{ size: 9 }} }} }} }} }}
}});
</script>
</body>
</html>"""

def main():
    print("=" * 60)
    print("ANÁLISE DE ATTACHMENTS + IA → HTML")
    print("=" * 60)

    print("\n[1/4] Coletando dados do MongoDB...")
    docs = coletar_dados()
    print(f"  Total: {len(docs)} documentos")

    print("[2/4] Gerando resumo estatístico...")
    resumo = gerar_resumo_estatistico(docs)
    print(f"  Sucesso: {resumo['total_sucesso_validacao']} ({resumo['pct_sucesso']}%)")

    print("[3/4] Enviando para análise da IA...")
    analise_ia = enviar_para_ia(resumo)
    if analise_ia:
        print("  Resposta recebida da IA.")
    else:
        print("  [AVISO] Não foi possível obter resposta da IA.")

    print("[4/4] Gerando dashboard HTML...")
    html_content = gerar_html(resumo, analise_ia)

    now = datetime.now()
    version_folder = os.path.join(DASHBOARDS_DIR, now.strftime("%Y-%m-%d_%H%M"))
    os.makedirs(version_folder, exist_ok=True)

    output_file = os.path.join(version_folder, "analise_attachments.html")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\nDashboard salvo em: {output_file}")
    print(f"Pasta de versionamento: {DASHBOARDS_DIR}/")

if __name__ == "__main__":
    main()
