const $ = (id) => document.getElementById(id);
const stateNames = {
  improving: "Mejorando", bending: "Se dobla", falling: "Cayendo",
  healthy: "Saludable", weak: "Vulnerable", stable: "Estable",
  not_enough_data: "Sin tendencia suficiente",
};
const pillarNames = {
  liquidity: "Liquidez", cash_generation: "Generación de caja",
  payment_discipline: "Pagos", collections: "Cobros", debt_burden: "Carga de deuda",
};
const monthFormat = new Intl.DateTimeFormat("es-ES", { month: "short", year: "numeric", timeZone: "UTC" });
const number = (value, digits = 1) => value == null ? "—" : Number(value).toLocaleString("es-ES", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const signed = (value) => value == null ? "—" : `${value > 0 ? "+" : ""}${number(value)}`;
const percent = (value, digits = 0) => value == null ? "—" : `${number(value * 100, digits)} %`;
const monthName = (value) => monthFormat.format(new Date(`${value.slice(0, 10)}T12:00:00Z`));

let groups = [];
let detail = null;
let selectedMonth = null;
let requestId = 0;

function showStatus(message) {
  $("status").textContent = message;
  $("status").hidden = false;
  $("content").hidden = true;
}

function renderGroups() {
  const query = $("search").value.trim().toLocaleLowerCase("es");
  const shown = groups.filter((group) => group.group_id.toLocaleLowerCase("es").includes(query));
  const list = $("group-list");
  list.replaceChildren();
  for (const group of shown) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "group-item";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(detail?.group_id === group.group_id));
    const id = document.createElement("span");
    id.className = "group-id";
    id.textContent = group.group_id;
    const score = document.createElement("span");
    score.className = "group-score";
    score.textContent = number(group.level, 0);
    const state = document.createElement("span");
    state.className = "group-state";
    state.textContent = stateNames[group.state] || group.state;
    button.append(id, score, state);
    button.addEventListener("click", () => loadGroup(group.group_id));
    list.append(button);
  }
  if (!shown.length) {
    const empty = document.createElement("p");
    empty.className = "group-state";
    empty.style.padding = "12px";
    empty.textContent = "No hay grupos con ese identificador.";
    list.append(empty);
  }
}

async function loadGroup(groupId) {
  const currentRequest = ++requestId;
  showStatus(`Cargando ${groupId}…`);
  try {
    const response = await fetch(`/api/v1/real-groups/${encodeURIComponent(groupId)}`);
    if (!response.ok) throw new Error(`No se pudo cargar ${groupId} (HTTP ${response.status}).`);
    const result = await response.json();
    if (currentRequest !== requestId) return;
    detail = result;
    selectedMonth = result.scores.at(-1)?.month;
    $("chart").replaceChildren();
    const select = $("month-select");
    select.replaceChildren();
    for (const row of [...result.scores].reverse()) {
      const option = document.createElement("option");
      option.value = row.month;
      option.textContent = monthName(row.month);
      select.append(option);
    }
    select.value = selectedMonth;
    renderGroups();
    renderDetail();
  } catch (error) {
    if (currentRequest === requestId) showStatus(`${error.message} Recarga la página para reintentar.`);
  }
}

function fact(label, value) {
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.textContent = value;
  $("facts").append(dt, dd);
}

function note(message, warning = false) {
  const item = document.createElement("div");
  item.className = `quality-note${warning ? " warn" : ""}`;
  item.textContent = message;
  $("quality-notes").append(item);
}

function renderChart(scores) {
  const chart = $("chart");
  const initialView = !chart.querySelector("svg");
  const previousScroll = chart.scrollLeft;
  const width = 900, height = 236, left = 33, right = 12, top = 12, bottom = 31;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const x = (i) => left + (scores.length === 1 ? 0 : i * plotWidth / (scores.length - 1));
  const y = (level) => top + (100 - level) * plotHeight / 100;
  const selectedIndex = scores.findIndex((row) => row.month === selectedMonth);
  const grid = [0, 40, 70, 100].map((level) => `<line class="${level === 40 || level === 70 ? "threshold" : "grid"}" x1="${left}" x2="${width - right}" y1="${y(level)}" y2="${y(level)}"/><text x="0" y="${y(level) + 4}">${level}</text>`).join("");
  const months = scores.map((row, i) => i % 4 === 0 || i === scores.length - 1 ? `<text x="${x(i)}" y="${height - 4}" text-anchor="${i === 0 ? "start" : i === scores.length - 1 ? "end" : "middle"}">${monthName(row.month)}</text>` : "").join("");
  const segments = [];
  let segment = [];
  scores.forEach((row, i) => {
    if (row.level == null) {
      if (segment.length) segments.push(segment);
      segment = [];
    } else segment.push(`${x(i)},${y(row.level)}`);
  });
  if (segment.length) segments.push(segment);
  const paths = segments.map((points) => `<polyline class="path" points="${points.join(" ")}"/>`).join("");
  const selected = selectedIndex >= 0 ? `<line class="selected-guide" x1="${x(selectedIndex)}" x2="${x(selectedIndex)}" y1="${top}" y2="${height - bottom}"/>` : "";
  const points = scores.map((row, i) => row.level == null ? "" : `<circle class="point ${i === selectedIndex ? "selected" : ""}" cx="${x(i)}" cy="${y(row.level)}" r="${i === selectedIndex ? 5 : 3}"/><circle class="hit" data-index="${i}" cx="${x(i)}" cy="${y(row.level)}" r="13"/>`).join("");
  chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">${grid}${selected}${paths}${points}${months}</svg>`;
  chart.scrollLeft = initialView ? chart.scrollWidth : previousScroll;
  chart.setAttribute("aria-label", `Evolución de ${detail.group_id}: ${scores.filter((row) => row.level != null).length} meses con score de ${scores.length}. Mes seleccionado: ${monthName(selectedMonth)}.`);
  chart.querySelectorAll(".hit").forEach((circle) => circle.addEventListener("click", () => {
    selectedMonth = scores[Number(circle.dataset.index)].month;
    $("month-select").value = selectedMonth;
    renderDetail();
  }));
}

function renderDetail() {
  const row = detail.scores.find((item) => item.month === selectedMonth);
  if (!row) return;
  $("status").hidden = true;
  $("content").hidden = false;
  $("group-title").textContent = detail.group_id;
  $("month-label").textContent = `Observación de ${monthName(row.month)} · grupo de empresas`;
  $("state-badge").textContent = stateNames[row.state] || row.state;
  $("state-badge").dataset.state = row.state;
  $("score-value").textContent = number(row.level, 0);
  $("trend-value").textContent = row.trend == null ? "—" : `${signed(row.trend)} pts/mes`;
  $("trend-value").className = row.trend > 0 ? "positive" : row.trend < 0 ? "negative" : "";
  $("coverage-value").textContent = percent(row.coverage);
  $("observed-value").textContent = number(row.months_observed, 0);
  renderChart(detail.scores);

  const body = $("drivers-body");
  body.replaceChildren();
  const drivers = detail.drivers.filter((item) => item.month === selectedMonth);
  for (const name of Object.keys(pillarNames)) {
    const driver = drivers.find((item) => item.pillar === name);
    const tr = document.createElement("tr");
    const cells = [pillarNames[name], number(driver?.score), signed(driver?.score == null ? null : driver.contribution), signed(driver?.score == null ? null : driver.delta_contribution)];
    cells.forEach((value, i) => {
      const td = document.createElement("td");
      td.textContent = value;
      if (i > 1 && value !== "—") td.className = value.startsWith("+") ? "positive" : value.startsWith("-") ? "negative" : "";
      tr.append(td);
    });
    body.append(tr);
  }
  $("cap-note").hidden = !row.is_capped;

  $("facts").replaceChildren();
  fact("Colchón de caja", row.buffer_days == null ? "—" : `${number(row.buffer_days, 0)} días`);
  fact("Margen operativo (3 m)", percent(row.operating_margin, 1));
  fact("Retraso de pagos", row.ap_days_beyond_terms == null ? "—" : `${number(row.ap_days_beyond_terms)} días`);
  fact("Retraso de cobros", row.ar_days_beyond_terms == null ? "—" : `${number(row.ar_days_beyond_terms)} días`);
  fact("Entrada operativa conocida (3 m)", row.known_inflow_3m == null ? "—" : number(row.known_inflow_3m, 0));
  fact("Movimientos sin categoría (3 m)", percent(row.uncategorized_share, 1));
  fact("Varias divisas", row.currency_mixed ? "Sí" : "No");

  $("quality-notes").replaceChildren();
  if (row.level == null) note("Este mes no cumple los mínimos de observación para emitir un nivel.", true);
  if (row.trend == null) note("Todavía no hay seis niveles consecutivos para calcular una tendencia.");
  if (row.currency_mixed) note("El grupo mezcla divisas. Los importes agregados no se convierten de moneda.", true);
  if (row.uncategorized_share != null && row.uncategorized_share > 0.2) note(`${percent(row.uncategorized_share, 1)} del volumen de movimientos no tiene categoría; no se le ha asignado una por inferencia.`, true);
  if (row.coverage < 1) note(`Solo está disponible el ${percent(row.coverage)} del peso de los pilares; los pesos presentes se renormalizan.`);
  if (!$("quality-notes").children.length) note("No se han detectado las limitaciones de calidad señaladas por este visor.");
}

async function init() {
  $("search").addEventListener("input", renderGroups);
  $("month-select").addEventListener("change", (event) => {
    selectedMonth = event.target.value;
    renderDetail();
  });
  try {
    const response = await fetch("/api/v1/real-groups?limit=500");
    if (!response.ok) throw new Error(`No se pudo consultar la API (HTTP ${response.status}).`);
    const result = await response.json();
    if (!result.available) {
      $("group-count").textContent = "Sin datos calculados";
      showStatus("Aún no hay scores reales. Ejecuta «make score-baseline» en la raíz del proyecto y reinicia la API.");
      return;
    }
    groups = result.data;
    $("group-count").textContent = `${result.total} grupos · ${groups.filter((group) => group.level != null).length} con nivel en el último mes`;
    renderGroups();
    if (groups.length) await loadGroup(groups[0].group_id);
    else showStatus("El mart de scores existe, pero no contiene grupos.");
  } catch (error) {
    $("group-count").textContent = "Error al cargar";
    showStatus(`${error.message} Comprueba que la API esté activa y recarga la página.`);
  }
}

init();
