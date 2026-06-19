import os
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
DB_NAME = "ClaimEngine"
COLLECTION = "Attachment"
FILTER_DATE = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

DASHBOARDS_DIR = "dashboards"
os.makedirs(DASHBOARDS_DIR, exist_ok=True)

def coletar_dados():
    client = MongoClient(MONGO_URI)
    collection = client[DB_NAME][COLLECTION]
    docs = list(collection.find({"CreatedAt": {"$gte": FILTER_DATE}}))
    client.close()
    print(f"Total de documentos coletados: {len(docs)}")
    return docs

def processar_dados(docs):
    dados = {
        "total": len(docs),
        "status_counter": Counter(),
        "doc_type_counter": Counter(),
        "sucesso_por_tipo": Counter(),
        "falha_por_tipo": Counter(),
        "failed_por_tipo": Counter(),
        "erros_tipificacao": Counter(),
        "metadados_ausentes": defaultdict(Counter),
        "metadados_invalidos": defaultdict(Counter),
        "metadados_adicionais": defaultdict(Counter),
        "campos_required_por_tipo": defaultdict(Counter),
        "campos_preenchidos_por_tipo": defaultdict(Counter),
        "campos_validos_por_tipo": defaultdict(Counter),
        "campos_validados_por_tipo": defaultdict(Counter),
        "file_type_counter": Counter(),
        "origin_counter": Counter(),
        "tempo_processamento": [],
        "tamanho_arquivo": [],
        "docs_por_dia": Counter(),
        "sucesso_por_dia": Counter(),
    }

    for doc in docs:
        status = doc.get("status", "Unknown")
        dados["status_counter"][status] += 1

        validation_success = doc.get("metadataValidationSuccess", False)
        technical = doc.get("technicalDetails") or {}
        error_msg = technical.get("Error", "")

        doc_type_names = doc.get("documentTypeNames") or []
        doc_type = doc_type_names[0] if doc_type_names else "Não identificado"
        dados["doc_type_counter"][doc_type] += 1

        if validation_success:
            dados["sucesso_por_tipo"][doc_type] += 1
        else:
            dados["falha_por_tipo"][doc_type] += 1

        if status == "Failed":
            dados["failed_por_tipo"][doc_type] += 1
            if error_msg:
                dados["erros_tipificacao"][error_msg[:120]] += 1

        dados["file_type_counter"][technical.get("FileType", "N/A")] += 1
        dados["origin_counter"][doc.get("origin", "N/A")] += 1

        total_time = technical.get("TotalTime")
        if total_time:
            dados["tempo_processamento"].append(total_time)

        size_kb = doc.get("sizeKb")
        if size_kb:
            dados["tamanho_arquivo"].append(size_kb)

        created = doc.get("CreatedAt")
        if created:
            dia = created.strftime("%Y-%m-%d")
            dados["docs_por_dia"][dia] += 1
            if validation_success:
                dados["sucesso_por_dia"][dia] += 1

        if error_msg and "ausentes" in error_msg.lower():
            for parte in error_msg.split("\n"):
                if "ausentes" in parte.lower():
                    campos_str = parte.split("›")[-1] if "›" in parte else ""
                    for campo in campos_str.split(","):
                        campo = campo.strip()
                        if campo:
                            dados["metadados_ausentes"][doc_type][campo] += 1

        if error_msg and "inválidos" in error_msg.lower():
            for parte in error_msg.split("\n"):
                if "inválidos" in parte.lower():
                    campos_str = parte.split("›")[-1] if "›" in parte else ""
                    for campo in campos_str.split(","):
                        campo = campo.strip()
                        if campo:
                            dados["metadados_invalidos"][doc_type][campo] += 1

        metadata_list = doc.get("metadata") or []
        for meta in metadata_list:
            meta_doc_type = meta.get("DocumentType", doc_type)
            for field in meta.get("Fields", []):
                field_type = field.get("Type", "")
                key = field.get("Key", "")
                value = field.get("Value")
                valid = field.get("Valid")

                if field_type == "Required":
                    dados["campos_required_por_tipo"][meta_doc_type][key] += 1
                    if value not in [None, ""]:
                        dados["campos_preenchidos_por_tipo"][meta_doc_type][key] += 1
                    if valid is not None:
                        dados["campos_validados_por_tipo"][meta_doc_type][key] += 1
                        if valid is True:
                            dados["campos_validos_por_tipo"][meta_doc_type][key] += 1

                if field_type == "Additional":
                    dados["metadados_adicionais"][meta_doc_type][key] += 1

    return dados

def gerar_html(dados):
    total = dados["total"]
    failed_status = dados["status_counter"].get("Failed", 0)
    total_sem_failed = total - failed_status
    sucesso = sum(dados["sucesso_por_tipo"].values())
    falha = total_sem_failed - sucesso
    pct_sucesso = round(sucesso / total_sem_failed * 100, 2) if total_sem_failed > 0 else 0
    tempo_medio = round(sum(dados["tempo_processamento"]) / len(dados["tempo_processamento"]), 1) if dados["tempo_processamento"] else 0

    status_data = json.dumps([{"status": k, "count": v} for k, v in dados["status_counter"].most_common()])

    tipos_data = []
    for tipo, total_tipo in dados["doc_type_counter"].most_common(25):
        ok = dados["sucesso_por_tipo"].get(tipo, 0)
        nok = total_tipo - ok
        pct = round(ok / total_tipo * 100, 1) if total_tipo > 0 else 0
        tipos_data.append({"tipo": tipo, "total": total_tipo, "ok": ok, "nok": nok, "pct": pct})
    tipos_json = json.dumps(tipos_data, ensure_ascii=False)

    dias = sorted(dados["docs_por_dia"].keys())
    evolucao_data = []
    for dia in dias:
        t = dados["docs_por_dia"][dia]
        s = dados["sucesso_por_dia"].get(dia, 0)
        evolucao_data.append({"dia": dia, "total": t, "ok": s, "pct": round(s / t * 100, 1) if t > 0 else 0})
    evolucao_json = json.dumps(evolucao_data)

    erros_data = [{"erro": e, "freq": f} for e, f in dados["erros_tipificacao"].most_common(15)]
    erros_json = json.dumps(erros_data, ensure_ascii=False)

    heatmap_tipos = sorted(set(list(dados["metadados_ausentes"].keys()) + list(dados["metadados_invalidos"].keys())))[:15]
    heatmap_campos = set()
    for tipo in heatmap_tipos:
        for campo in list(dados["metadados_ausentes"].get(tipo, {}).keys())[:10]:
            heatmap_campos.add(campo)
        for campo in list(dados["metadados_invalidos"].get(tipo, {}).keys())[:10]:
            heatmap_campos.add(campo)
    heatmap_campos = sorted(heatmap_campos)[:20]
    heatmap_matrix = []
    for tipo in heatmap_tipos:
        row = []
        for campo in heatmap_campos:
            val = dados["metadados_ausentes"].get(tipo, {}).get(campo, 0) + dados["metadados_invalidos"].get(tipo, {}).get(campo, 0)
            row.append(val)
        heatmap_matrix.append(row)
    heatmap_json = json.dumps({"tipos": heatmap_tipos, "campos": heatmap_campos, "matrix": heatmap_matrix}, ensure_ascii=False)

    file_types_json = json.dumps([{"type": k, "count": v} for k, v in dados["file_type_counter"].most_common()])

    detalhes_tipo_rows = ""
    for tipo, total_tipo in dados["doc_type_counter"].most_common():
        ok = dados["sucesso_por_tipo"].get(tipo, 0)
        nok = total_tipo - ok
        pct = round(ok / total_tipo * 100, 1) if total_tipo > 0 else 0
        failed = dados["failed_por_tipo"].get(tipo, 0)
        ausentes = dados["metadados_ausentes"].get(tipo, {})
        invalidos = dados["metadados_invalidos"].get(tipo, {})
        problemas_list = []
        for campo, freq in Counter(ausentes).most_common(5):
            problemas_list.append(f"Ausente: {campo} ({freq}x)")
        for campo, freq in Counter(invalidos).most_common(5):
            problemas_list.append(f"Inválido: {campo} ({freq}x)")
        problemas_str = "<br>".join(problemas_list) if problemas_list else "—"
        color_class = "ok-row" if pct >= 80 else "warn-row" if pct >= 50 else "bad-row"
        detalhes_tipo_rows += f'<tr class="{color_class}"><td>{tipo}</td><td>{total_tipo}</td><td>{ok}</td><td>{nok}</td><td>{pct}%</td><td>{failed}</td><td class="problemas">{problemas_str}</td></tr>\n'

    required_rows = ""
    for tipo in sorted(dados["campos_required_por_tipo"].keys()):
        for campo, total_campo in dados["campos_required_por_tipo"][tipo].most_common():
            preenchidos = dados["campos_preenchidos_por_tipo"].get(tipo, {}).get(campo, 0)
            pct_p = round(preenchidos / total_campo * 100, 1) if total_campo > 0 else 0
            validados = dados["campos_validados_por_tipo"].get(tipo, {}).get(campo, 0)
            validos = dados["campos_validos_por_tipo"].get(tipo, {}).get(campo, 0)
            pct_v = round(validos / validados * 100, 1) if validados > 0 else "—"
            color = "ok-row" if pct_p >= 90 else "warn-row" if pct_p >= 60 else "bad-row"
            required_rows += f'<tr class="{color}"><td>{tipo}</td><td>{campo}</td><td>{total_campo}</td><td>{preenchidos}</td><td>{pct_p}%</td><td>{validados}</td><td>{validos}</td><td>{pct_v}{"%" if isinstance(pct_v, float) else ""}</td></tr>\n'

    adicionais_rows = ""
    for tipo in sorted(dados["metadados_adicionais"].keys()):
        required_campos = set(dados["campos_required_por_tipo"].get(tipo, {}).keys())
        for campo, freq in dados["metadados_adicionais"][tipo].most_common(10):
            correlacao = ""
            campo_lower = campo.lower().replace("_", " ")
            for req in required_campos:
                if req.lower() in campo_lower or campo_lower in req.lower():
                    correlacao = f"→ {req}"
                    break
            adicionais_rows += f'<tr><td>{tipo}</td><td>{campo}</td><td>{freq}</td><td class="correlacao">{correlacao}</td></tr>\n'

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Attachments - {now_str}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', Tahoma, sans-serif; background: #1a1a2e; color: #eee; padding: 20px; }}
.header {{ text-align: center; padding: 30px 0; }}
.header h1 {{ font-size: 28px; color: #00d4aa; }}
.header p {{ color: #888; margin-top: 8px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 30px 0; }}
.kpi {{ background: #16213e; border-radius: 12px; padding: 20px; text-align: center; border: 1px solid #0f3460; }}
.kpi .value {{ font-size: 32px; font-weight: bold; color: #00d4aa; }}
.kpi .label {{ font-size: 13px; color: #888; margin-top: 5px; }}
.kpi.danger .value {{ color: #e74c3c; }}
.kpi.warning .value {{ color: #f39c12; }}
.charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(450px, 1fr)); gap: 20px; margin: 30px 0; }}
.chart-card {{ background: #16213e; border-radius: 12px; padding: 20px; border: 1px solid #0f3460; }}
.chart-card h3 {{ color: #00d4aa; margin-bottom: 15px; font-size: 15px; }}
.chart-card canvas {{ max-height: 350px; }}
.full-width {{ grid-column: 1 / -1; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th {{ background: #0f3460; color: #00d4aa; padding: 10px 8px; text-align: left; position: sticky; top: 0; }}
td {{ padding: 8px; border-bottom: 1px solid #1a1a2e; }}
tr:hover {{ background: #1e3a5f; }}
.ok-row td:first-child {{ border-left: 3px solid #2ecc71; }}
.warn-row td:first-child {{ border-left: 3px solid #f39c12; }}
.bad-row td:first-child {{ border-left: 3px solid #e74c3c; }}
.problemas {{ font-size: 11px; color: #ccc; max-width: 400px; }}
.correlacao {{ color: #00d4aa; font-weight: bold; }}
.section {{ margin: 40px 0; }}
.section h2 {{ color: #00d4aa; margin-bottom: 15px; font-size: 20px; border-bottom: 1px solid #0f3460; padding-bottom: 10px; }}
.table-container {{ background: #16213e; border-radius: 12px; padding: 15px; border: 1px solid #0f3460; max-height: 500px; overflow-y: auto; }}
.filter-input {{ background: #0f3460; border: 1px solid #00d4aa; color: #eee; padding: 8px 12px; border-radius: 6px; margin-bottom: 10px; width: 300px; }}
</style>
</head>
<body>

<div class="header">
<h1>📊 Dashboard de Análise de Attachments</h1>
<p>Gerado em {now_str} | Período: a partir de 12/05/2026</p>
</div>

<div class="kpis">
<div class="kpi"><div class="value">{total}</div><div class="label">Total Documentos</div></div>
<div class="kpi"><div class="value">{total_sem_failed}</div><div class="label">Base (sem Failed)</div></div>
<div class="kpi"><div class="value">{sucesso}</div><div class="label">OK (Validação)</div></div>
<div class="kpi danger"><div class="value">{falha}</div><div class="label">Não OK</div></div>
<div class="kpi"><div class="value">{pct_sucesso}%</div><div class="label">Taxa de Sucesso</div></div>
<div class="kpi danger"><div class="value">{failed_status}</div><div class="label">Failed (Excluídos)</div></div>
<div class="kpi warning"><div class="value">{tempo_medio}s</div><div class="label">Tempo Médio</div></div>
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
<h3>Top 25 Tipos de Documento - OK vs Não OK</h3>
<canvas id="chartTipos" height="120"></canvas>
</div>
<div class="chart-card full-width">
<h3>Evolução Diária - Volume e % Sucesso</h3>
<canvas id="chartEvolucao" height="80"></canvas>
</div>
<div class="chart-card full-width">
<h3>Heatmap de Problemas por Tipo (Ausentes + Inválidos)</h3>
<canvas id="chartHeatmap" height="100"></canvas>
</div>
<div class="chart-card">
<h3>Tipo de Arquivo</h3>
<canvas id="chartFileType"></canvas>
</div>
<div class="chart-card">
<h3>Top Erros de Tipificação</h3>
<canvas id="chartErros" height="200"></canvas>
</div>
</div>

<div class="section">
<h2>📋 Detalhamento por Tipo de Documento</h2>
<input type="text" class="filter-input" id="filterTipo" placeholder="Filtrar por tipo..." onkeyup="filterTable('tableTipos', 0)">
<div class="table-container">
<table id="tableTipos">
<thead><tr><th>Tipo</th><th>Total</th><th>OK</th><th>Não OK</th><th>% OK</th><th>Failed</th><th>Principais Problemas</th></tr></thead>
<tbody>{detalhes_tipo_rows}</tbody>
</table>
</div>
</div>

<div class="section">
<h2>📊 Taxa de Preenchimento - Campos Required</h2>
<input type="text" class="filter-input" id="filterRequired" placeholder="Filtrar por tipo ou campo..." onkeyup="filterTable('tableRequired', -1)">
<div class="table-container">
<table id="tableRequired">
<thead><tr><th>Tipo</th><th>Campo</th><th>Total</th><th>Preenchidos</th><th>% Preench.</th><th>Validados</th><th>Válidos</th><th>% Válidos</th></tr></thead>
<tbody>{required_rows}</tbody>
</table>
</div>
</div>

<div class="section">
<h2>🔗 Metadados Adicionais (Possíveis Correlações)</h2>
<div class="table-container">
<table id="tableAdicionais">
<thead><tr><th>Tipo</th><th>Campo Additional</th><th>Frequência</th><th>Correlação Required</th></tr></thead>
<tbody>{adicionais_rows}</tbody>
</table>
</div>
</div>

<script>
const statusData = {status_data};
const tiposData = {tipos_json};
const evolucaoData = {evolucao_json};
const errosData = {erros_json};
const heatmapData = {heatmap_json};
const fileTypesData = {file_types_json};

new Chart(document.getElementById('chartPie'), {{
    type: 'doughnut',
    data: {{
        labels: ['OK ({sucesso})', 'Não OK ({falha})'],
        datasets: [{{ data: [{sucesso}, {falha}], backgroundColor: ['#2ecc71', '#e74c3c'], borderWidth: 0 }}]
    }},
    options: {{ plugins: {{ legend: {{ labels: {{ color: '#eee' }} }} }} }}
}});

new Chart(document.getElementById('chartStatus'), {{
    type: 'bar',
    data: {{
        labels: statusData.map(d => d.status),
        datasets: [{{ data: statusData.map(d => d.count), backgroundColor: statusData.map(d => d.status === 'Typified' ? '#2ecc71' : d.status === 'Failed' ? '#e74c3c' : '#f39c12') }}]
    }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ ticks: {{ color: '#eee' }} }}, y: {{ ticks: {{ color: '#eee' }} }} }} }}
}});

new Chart(document.getElementById('chartTipos'), {{
    type: 'bar',
    data: {{
        labels: tiposData.map(d => d.tipo),
        datasets: [
            {{ label: 'OK', data: tiposData.map(d => d.ok), backgroundColor: '#2ecc71' }},
            {{ label: 'Não OK', data: tiposData.map(d => d.nok), backgroundColor: '#e74c3c' }}
        ]
    }},
    options: {{ indexAxis: 'y', plugins: {{ legend: {{ labels: {{ color: '#eee' }} }} }}, scales: {{ x: {{ stacked: true, ticks: {{ color: '#eee' }} }}, y: {{ stacked: true, ticks: {{ color: '#eee', font: {{ size: 10 }} }} }} }} }}
}});

new Chart(document.getElementById('chartEvolucao'), {{
    type: 'bar',
    data: {{
        labels: evolucaoData.map(d => d.dia),
        datasets: [
            {{ type: 'bar', label: 'Total', data: evolucaoData.map(d => d.total), backgroundColor: '#3498db', yAxisID: 'y' }},
            {{ type: 'bar', label: 'OK', data: evolucaoData.map(d => d.ok), backgroundColor: '#2ecc71', yAxisID: 'y' }},
            {{ type: 'line', label: '% OK', data: evolucaoData.map(d => d.pct), borderColor: '#f39c12', borderWidth: 2, pointRadius: 3, yAxisID: 'y1', fill: false }}
        ]
    }},
    options: {{ scales: {{ y: {{ position: 'left', ticks: {{ color: '#eee' }} }}, y1: {{ position: 'right', min: 0, max: 100, ticks: {{ color: '#f39c12' }} }}, x: {{ ticks: {{ color: '#eee' }} }} }}, plugins: {{ legend: {{ labels: {{ color: '#eee' }} }} }} }}
}});

const heatCtx = document.getElementById('chartHeatmap').getContext('2d');
const heatLabelsY = heatmapData.tipos;
const heatLabelsX = heatmapData.campos;
const heatMatrix = heatmapData.matrix;
const heatDatasets = heatLabelsY.map((tipo, i) => ({{
    label: tipo,
    data: heatMatrix[i],
    backgroundColor: heatMatrix[i].map(v => v === 0 ? '#1a1a2e' : v < 5 ? '#f39c12' : v < 15 ? '#e67e22' : '#e74c3c'),
}}));
new Chart(heatCtx, {{
    type: 'bar',
    data: {{ labels: heatLabelsX, datasets: heatDatasets }},
    options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ ticks: {{ color: '#eee', font: {{ size: 8 }}, maxRotation: 45 }} }}, y: {{ ticks: {{ color: '#eee' }} }} }} }}
}});

new Chart(document.getElementById('chartFileType'), {{
    type: 'doughnut',
    data: {{
        labels: fileTypesData.map(d => d.type),
        datasets: [{{ data: fileTypesData.map(d => d.count), backgroundColor: ['#3498db', '#2ecc71', '#f39c12', '#e74c3c', '#9b59b6', '#1abc9c'] }}]
    }},
    options: {{ plugins: {{ legend: {{ labels: {{ color: '#eee' }} }} }} }}
}});

new Chart(document.getElementById('chartErros'), {{
    type: 'bar',
    data: {{
        labels: errosData.map(d => d.erro.substring(0, 50) + '...'),
        datasets: [{{ data: errosData.map(d => d.freq), backgroundColor: '#e67e22' }}]
    }},
    options: {{ indexAxis: 'y', plugins: {{ legend: {{ display: false }}, tooltip: {{ callbacks: {{ title: (items) => errosData[items[0].dataIndex].erro }} }} }}, scales: {{ x: {{ ticks: {{ color: '#eee' }} }}, y: {{ ticks: {{ color: '#eee', font: {{ size: 8 }} }} }} }} }}
}});

function filterTable(tableId, colIndex) {{
    const input = event.target.value.toLowerCase();
    const rows = document.getElementById(tableId).getElementsByTagName('tbody')[0].getElementsByTagName('tr');
    for (let row of rows) {{
        const cells = row.getElementsByTagName('td');
        let match = false;
        if (colIndex >= 0) {{
            match = cells[colIndex].textContent.toLowerCase().includes(input);
        }} else {{
            for (let cell of cells) {{
                if (cell.textContent.toLowerCase().includes(input)) {{ match = true; break; }}
            }}
        }}
        row.style.display = match ? '' : 'none';
    }}
}}
</script>
</body>
</html>"""
    return html

def main():
    print("=" * 60)
    print("DASHBOARD HTML - ANÁLISE DE ATTACHMENTS")
    print("=" * 60)

    print("\n[1/3] Coletando dados do MongoDB...")
    docs = coletar_dados()

    print("[2/3] Processando dados...")
    dados = processar_dados(docs)

    print("[3/3] Gerando dashboard HTML...")
    html = gerar_html(dados)

    now = datetime.now()
    version_folder = os.path.join(DASHBOARDS_DIR, now.strftime("%Y-%m-%d_%H%M"))
    os.makedirs(version_folder, exist_ok=True)

    output_file = os.path.join(version_folder, "dashboard.html")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)

    total = dados["total"]
    failed_status = dados["status_counter"].get("Failed", 0)
    total_sem_failed = total - failed_status
    sucesso = sum(dados["sucesso_por_tipo"].values())
    print(f"\nTotal: {total} | Failed (excluídos): {failed_status} | Base: {total_sem_failed} | OK: {sucesso} ({round(sucesso/total_sem_failed*100,2) if total_sem_failed else 0}%) | Não OK: {total_sem_failed - sucesso}")
    print(f"\nDashboard salvo em: {output_file}")
    print(f"Pasta de versionamento: {DASHBOARDS_DIR}/")

if __name__ == "__main__":
    main()
