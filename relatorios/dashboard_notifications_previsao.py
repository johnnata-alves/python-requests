import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
DB_NAME = "ClaimEngine"
COLLECTION = "Notification"
TIMEZONE_OFFSET = timezone(timedelta(hours=3))
START_DATE = datetime(2025, 5, 25, 3, 0, 0, tzinfo=TIMEZONE_OFFSET)
PERIODOS_DIAS = [3, 7, 15, 30, 90]

DASHBOARDS_DIR = "dashboards"
os.makedirs(DASHBOARDS_DIR, exist_ok=True)

WEEKDAY_PT = {
    0: "Seg",
    1: "Ter",
    2: "Qua",
    3: "Qui",
    4: "Sex",
    5: "Sáb",
    6: "Dom",
}

def coletar_contagem_diaria():
    if not MONGO_URI:
        raise RuntimeError("Variável PRD_MONGO_URI não encontrada no ambiente.")

    client = MongoClient(MONGO_URI)
    collection = client[DB_NAME][COLLECTION]

    pipeline = [
        {"$match": {"CreatedAt": {"$gt": START_DATE}}},
        {
            "$project": {
                "dia": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$CreatedAt",
                        "timezone": "+03:00",
                    }
                }
            }
        },
        {"$group": {"_id": "$dia", "total": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]

    rows = list(collection.aggregate(pipeline, allowDiskUse=True))
    client.close()

    return {row["_id"]: row["total"] for row in rows}

def montar_serie_diaria(counts_by_day):
    start_local = START_DATE.astimezone(TIMEZONE_OFFSET).date()
    end_local = datetime.now(TIMEZONE_OFFSET).date()

    if end_local < start_local:
        return []

    serie = []
    current = start_local
    while current <= end_local:
        day_key = current.strftime("%Y-%m-%d")
        total = int(counts_by_day.get(day_key, 0))
        prev_day_key = (current - timedelta(days=7)).strftime("%Y-%m-%d")
        previous_week_count = (
            int(counts_by_day.get(prev_day_key, 0)) if prev_day_key in counts_by_day else None
        )
        weekday = current.weekday()
        serie.append(
            {
                "date": day_key,
                "count": total,
                "previousWeekCount": previous_week_count,
                "weekday": weekday,
                "weekdayName": WEEKDAY_PT[weekday],
            }
        )
        current += timedelta(days=1)

    return serie

def calcular_previsao_por_semana(serie):
    buckets = defaultdict(list)
    for item in serie:
        buckets[item["weekday"]].append(item["count"])

    media_por_dia_semana = {}
    for weekday in range(7):
        valores = buckets.get(weekday, [])
        media = round(sum(valores) / len(valores), 2) if valores else 0
        media_por_dia_semana[weekday] = media

    for item in serie:
        item["forecast"] = media_por_dia_semana[item["weekday"]]

    return media_por_dia_semana

def montar_payload(serie, media_por_dia_semana):
    total_geral = sum(item["count"] for item in serie)

    return {
        "generatedAt": datetime.now(TIMEZONE_OFFSET).isoformat(),
        "source": {
            "db": DB_NAME,
            "collection": COLLECTION,
            "createdAtFilter": {"$gt": START_DATE.isoformat()},
            "timezone": "+03:00",
        },
        "periods": PERIODOS_DIAS,
        "summary": {
            "totalNotifications": total_geral,
            "daysInSeries": len(serie),
            "dailyAverage": round(total_geral / len(serie), 2) if serie else 0,
            "maxDay": max((item["count"] for item in serie), default=0),
        },
        "weekdayHistoricalAverage": {
            WEEKDAY_PT[dia]: media_por_dia_semana.get(dia, 0) for dia in range(7)
        },
        "dailySeries": serie,
    }

def gerar_html(payload):
    payload_json = json.dumps(payload, ensure_ascii=False)
    generated_at = datetime.now(TIMEZONE_OFFSET).strftime("%d/%m/%Y %H:%M")

    template = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Notification - Volume x Previsão</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg-1: #e9fcfc;
  --bg-2: #fef8ef;
  --card: rgba(255, 255, 255, 0.78);
  --e-global-color-primary: #00BABE;
  --e-global-color-secondary: #00A3B3;
  --e-global-color-text: #5f6668;
  --e-global-color-accent: #FDBB63;
  --ink: var(--e-global-color-text);
  --muted: #5f6668;
  --stroke: rgba(0, 163, 179, 0.18);
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: 'Poppins', sans-serif;
  color: var(--ink);
  background:
    radial-gradient(circle at 10% 20%, rgba(0, 186, 190, 0.18), transparent 32%),
    radial-gradient(circle at 90% 0%, rgba(253, 187, 99, 0.2), transparent 30%),
    linear-gradient(120deg, var(--bg-1), var(--bg-2));
  min-height: 100vh;
}}
.container {{
  width: min(1400px, 96vw);
  margin: 24px auto 36px;
}}
.header {{
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}}
.header-left {{
  display: flex;
  align-items: center;
  gap: 14px;
}}
.brand-logo {{
  width: 158px;
  height: 54px;
  object-fit: contain;
  display: block;
  filter: drop-shadow(0px 0px 5px rgba(0, 163, 179, 0.9));
}}
.title h1 {{
  margin: 0;
  font-size: clamp(1.3rem, 2.6vw, 2rem);
  letter-spacing: -0.02em;
  color: var(--e-global-color-secondary);
}}
.title p {{
  margin: 6px 0 0;
  color: var(--muted);
  font-weight: 600;
  font-size: .95rem;
}}
.controls {{
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--card);
  border: 1px solid var(--stroke);
  border-radius: 999px;
  padding: 8px 12px;
  box-shadow: 0 8px 24px rgba(0, 163, 179, 0.12);
}}
.controls label {{
  font-size: .85rem;
  color: var(--e-global-color-secondary);
  font-weight: 700;
}}
.controls select {{
  border: none;
  background: transparent;
  font: inherit;
  font-weight: 700;
  color: var(--ink);
  outline: none;
  cursor: pointer;
}}
.cards {{
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(4, minmax(180px, 1fr));
  margin: 16px 0 18px;
}}
.card {{
  background: var(--card);
  border: 1px solid var(--stroke);
  border-radius: 18px;
  padding: 14px 16px;
  backdrop-filter: blur(6px);
  box-shadow: 0 8px 24px rgba(0, 163, 179, 0.12);
}}
.card h3 {{
  margin: 0 0 6px;
  font-size: .82rem;
  color: var(--e-global-color-secondary);
  text-transform: uppercase;
  letter-spacing: .08em;
}}
.card .value {{
  margin: 0;
  font-size: clamp(1.3rem, 2.6vw, 1.9rem);
  font-weight: 800;
  letter-spacing: -0.02em;
}}
.chart-wrap {{
  width: 100%;
  background: var(--card);
  border: 1px solid var(--stroke);
  border-radius: 20px;
  padding: 14px 14px 8px;
  box-shadow: 0 12px 32px rgba(0, 163, 179, 0.14);
}}
.chart-head {{
  margin: 4px 4px 8px;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}}
.chart-head h2 {{
  margin: 0;
  font-size: 1rem;
  letter-spacing: -0.01em;
  color: var(--e-global-color-secondary);
}}
.chart-head p {{
  margin: 0;
  color: var(--muted);
  font-size: .9rem;
  font-weight: 600;
}}
canvas {{
  width: 100% !important;
  height: min(62vh, 520px) !important;
}}
@media (max-width: 980px) {{
  .cards {{ grid-template-columns: repeat(2, minmax(150px, 1fr)); }}
}}
@media (max-width: 640px) {{
  .container {{ width: 95vw; margin-top: 14px; }}
  .header {{ flex-direction: column; align-items: flex-start; }}
  .header-left {{ width: 100%; }}
  .brand-logo {{ width: 136px; height: 46px; }}
  .cards {{ grid-template-columns: 1fr; }}
  canvas {{ height: 54vh !important; }}
}}
</style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="header-left">
        <img class="brand-logo" src="https://blog.tooseguros.com.br/wp-content/uploads/2020/12/logo_white.png" alt="Logo Too Seguros">
        <div class="title">
          <h1>Avisos Recebidos por Dia x Previsão por Dia da Semana</h1>
          <p>Atualizado em __GENERATED_AT__</p>
        </div>
      </div>
      <div class="controls">
        <label for="periodSelect">Período</label>
        <select id="periodSelect"></select>
      </div>
    </div>

    <section class="cards">
      <article class="card">
        <h3>Total no período</h3>
        <p class="value" id="cardTotal">0</p>
      </article>
      <article class="card">
        <h3>Média diária real</h3>
        <p class="value" id="cardAvg">0</p>
      </article>
      <article class="card">
        <h3>Média prevista</h3>
        <p class="value" id="cardForecastAvg">0</p>
      </article>
      <article class="card">
        <h3>Pico diário</h3>
        <p class="value" id="cardMax">0</p>
      </article>
    </section>

    <section class="chart-wrap">
      <div class="chart-head">
        <h2>Comparativo diário</h2>
        <p>Barras: recebidos | Linha dourada: previsão histórica | Linha grafite: mesmo dia da semana anterior</p>
      </div>
      <canvas id="chartVolume"></canvas>
    </section>
  </div>

  <script id="dashboard-data" type="application/json">__PAYLOAD_JSON__</script>
  <script>
    const payload = JSON.parse(document.getElementById('dashboard-data').textContent);
    const periodSelect = document.getElementById('periodSelect');

    payload.periods.forEach(days => {
      const opt = document.createElement('option');
      opt.value = String(days);
      opt.textContent = `Últimos ${days} dias`;
      if (days === 30) opt.selected = true;
      periodSelect.appendChild(opt);
    });

    const chartCtx = document.getElementById('chartVolume').getContext('2d');
    const volumeChart = new Chart(chartCtx, {
      type: 'bar',
      data: { labels: [], datasets: [] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: '#5f6668', maxRotation: 0, autoSkip: true, maxTicksLimit: 20 }
          },
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(0, 163, 179, 0.14)' },
            ticks: { color: '#5f6668' }
          }
        },
        plugins: {
          legend: { labels: { color: '#5f6668', font: { weight: '700' } } },
          tooltip: {
            backgroundColor: 'rgba(0, 163, 179, 0.95)',
            titleFont: { weight: '700' },
            bodyFont: { weight: '600' },
            callbacks: {
              title: items => items?.[0]?.label || '',
              label: ctx => {
                const value = ctx.parsed.y;
                if (value === null || value === undefined || Number.isNaN(value)) {
                  return `${ctx.dataset.label}: sem histórico`;
                }
                return `${ctx.dataset.label}: ${Number(value).toFixed(2)}`;
              }
            }
          }
        },
        animation: { duration: 650, easing: 'easeOutQuart' }
      }
    });

    function sliceByDays(series, days) {
      if (!series.length) return [];
      const maxDate = new Date(series[series.length - 1].date + 'T00:00:00');
      const start = new Date(maxDate);
      start.setDate(start.getDate() - (days - 1));

      return series.filter(item => new Date(item.date + 'T00:00:00') >= start);
    }

    function fmtBrDate(iso) {
      const [y, m, d] = iso.split('-');
      return `${d}/${m}`;
    }

    function updateCards(data) {
      const total = data.reduce((acc, x) => acc + x.count, 0);
      const avg = data.length ? total / data.length : 0;
      const forecastAvg = data.length ? data.reduce((acc, x) => acc + x.forecast, 0) / data.length : 0;
      const max = data.reduce((acc, x) => Math.max(acc, x.count), 0);

      document.getElementById('cardTotal').textContent = total.toLocaleString('pt-BR');
      document.getElementById('cardAvg').textContent = avg.toFixed(2).replace('.', ',');
      document.getElementById('cardForecastAvg').textContent = forecastAvg.toFixed(2).replace('.', ',');
      document.getElementById('cardMax').textContent = max.toLocaleString('pt-BR');
    }

    function render(days) {
      const filtered = sliceByDays(payload.dailySeries, days);
      const labels = filtered.map(x => [fmtBrDate(x.date), x.weekdayName]);
      const values = filtered.map(x => x.count);
      const forecast = filtered.map(x => x.forecast);
      const previousWeek = filtered.map(x => x.previousWeekCount);

      volumeChart.data.labels = labels;
      volumeChart.data.datasets = [
        {
          type: 'bar',
          label: 'Avisos recebidos',
          data: values,
          backgroundColor: 'rgba(0, 186, 190, 0.72)',
          borderColor: '#00A3B3',
          borderWidth: 1.2,
          borderRadius: 8,
          borderSkipped: false,
          maxBarThickness: 38
        },
        {
          type: 'line',
          label: 'Previsão histórica',
          data: forecast,
          borderColor: '#FDBB63',
          backgroundColor: '#FDBB63',
          tension: 0.32,
          pointRadius: 3,
          pointHoverRadius: 5,
          borderWidth: 2.2
        },
        {
          type: 'line',
          label: 'Semana anterior (mesmo dia)',
          data: previousWeek,
          borderColor: '#5f6668',
          backgroundColor: '#5f6668',
          tension: 0.24,
          pointRadius: 3,
          pointHoverRadius: 5,
          spanGaps: false,
          borderWidth: 2.2
        }
      ];
      volumeChart.update();
      updateCards(filtered);
    }

    periodSelect.addEventListener('change', (e) => {
      render(Number(e.target.value));
    });

    render(Number(periodSelect.value));
  </script>
</body>
</html>
"""

    return (
      template.replace("{{", "{").replace("}}", "}")
        .replace("__GENERATED_AT__", generated_at)
        .replace("__PAYLOAD_JSON__", payload_json)
    )

def salvar_artefatos(payload, html):
    now = datetime.now(TIMEZONE_OFFSET)
    version_folder = os.path.join(DASHBOARDS_DIR, now.strftime("%Y-%m-%d_%H%M"))
    os.makedirs(version_folder, exist_ok=True)

    json_file = os.path.join(version_folder, "notifications_daily.json")
    html_file = os.path.join(version_folder, "dashboard_notifications.html")

    with open(json_file, "w", encoding="utf-8") as f_json:
        json.dump(payload, f_json, ensure_ascii=False, indent=2)

    with open(html_file, "w", encoding="utf-8") as f_html:
        f_html.write(html)

    return json_file, html_file

def main():
    print("=" * 68)
    print("DASHBOARD NOTIFICATION - VOLUME DIÁRIO x PREVISÃO HISTÓRICA")
    print("=" * 68)

    print("\n[1/4] Consultando Notification no MongoDB...")
    counts_by_day = coletar_contagem_diaria()
    print(f"Dias com registro: {len(counts_by_day)}")

    print("[2/4] Montando série diária contínua...")
    serie = montar_serie_diaria(counts_by_day)
    print(f"Dias na série: {len(serie)}")

    print("[3/4] Calculando médias históricas por dia da semana...")
    media_por_dia_semana = calcular_previsao_por_semana(serie)

    print("[4/4] Gerando JSON e HTML...")
    payload = montar_payload(serie, media_por_dia_semana)
    html = gerar_html(payload)
    json_file, html_file = salvar_artefatos(payload, html)

    print("\nArquivos gerados:")
    print(f"- JSON: {json_file}")
    print(f"- HTML: {html_file}")

if __name__ == "__main__":
    main()
