const SOURCES = {
  preflight: "../adapters/preflight-v1.1.json",
  readiness: "../adapters/condition-readiness-v1.1.json",
  results: "../analysis/processed-results-v1.1.json",
  execution: "../adapters/execution-readiness-v1.1.json",
};

const fallback = {
  preflight: {
    protocol_version: "v1.1",
    model_policy: "../protocol/model-policy-v1.1.json",
    ade: {
      orca: { status: "installed-not-ready" },
      "agent-orchestrator": { status: "installed-ready" },
      compozy: { status: "installed-not-ready" },
    },
    harness: {
      reference: { status: "contract-ready" },
      "openhands-sdk": { status: "dependency-resolution-failed" },
      "mini-swe-agent": { status: "installed-not-ready" },
    },
    agentskit: { off: { status: "contract-ready" }, on: { status: "installed-not-ready" } },
  },
  readiness: { protocol_version: "v1.1", ready_conditions: 0, blocked_conditions: 18, conditions: [] },
  results: { status: "no-results", summary: { runs: 0, evaluated_runs: 0, quality_pass_count: 0, excluded_runs: 0 }, metrics: {} },
  execution: { blocker_summary: { operator: 0, upstream: 3, protocol: 1 }, blockers: [], technical_conditions_ready: [] },
};

const $ = (selector) => document.querySelector(selector);
const label = (value) => value.replaceAll("-", " ");
const stateClass = (value) => value === "contract-ready" || value === "installed-ready" ? "state-ready" : "state-blocked";
const stateLabel = (value) => value === "contract-ready" ? "ready" : value === "installed-ready" ? "ready" : value === "dependency-resolution-failed" ? "dependency failed" : "blocked";

async function loadJson(path, key) {
  try {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status}`);
    return await response.json();
  } catch (error) {
    console.warn(`Dashboard source unavailable (${path}); using bounded fallback.`, error);
    return fallback[key];
  }
}

function componentEntries(preflight) {
  return [
    ...Object.entries(preflight.ade).map(([name, data]) => [`ADE / ${label(name)}`, data.status]),
    ...Object.entries(preflight.harness).map(([name, data]) => [`Harness / ${label(name)}`, data.status]),
    ...Object.entries(preflight.agentskit).map(([name, data]) => [`AgentsKit / ${name.toUpperCase()}`, data.status]),
  ];
}

function renderComponents(preflight) {
  const entries = componentEntries(preflight);
  const ready = entries.filter(([, status]) => stateClass(status) === "state-ready").length;
  $("#component-summary").textContent = `${ready} / ${entries.length} ready`;
  $("#component-list").innerHTML = entries.map(([name, status]) => `
    <div class="component-row">
      <span class="component-name">${name}</span>
      <span class="component-state ${stateClass(status)}">${stateLabel(status)}</span>
    </div>`).join("");
}

function factorChip(value) {
  const blocked = stateClass(value) === "state-blocked";
  return `<span class="factor-chip${blocked ? " blocked" : ""}">${blocked ? "blocked" : "ready"}</span>`;
}

function renderConditions(report, filter = "all") {
  const rows = (report.conditions || []).filter((condition) => filter === "all" || condition.condition_id.startsWith(`${filter}__`));
  $("#condition-empty").hidden = rows.length > 0;
  $("#condition-rows").innerHTML = rows.map((condition) => {
    const [ade, harness, agentskit] = condition.condition_id.split("__");
    const statuses = condition.factor_statuses;
    return `<tr>
      <td><span class="condition-id">${condition.condition_id}</span></td>
      <td>${factorChip(statuses.ade)}</td>
      <td>${factorChip(statuses.harness)}</td>
      <td>${factorChip(statuses.agentskit)}</td>
      <td class="gate-cell ${condition.ready ? "state-ready" : "state-blocked"}">${condition.ready ? "ready" : "blocked"}</td>
    </tr>`;
  }).join("");
}

function renderReadiness(preflight, report) {
  const total = report.conditions?.length || 18;
  const ready = report.ready_conditions ?? 0;
  const blocked = report.blocked_conditions ?? total - ready;
  $("#protocol-label").textContent = report.protocol_version || preflight.protocol_version;
  $("#ready-count").textContent = ready;
  $("#condition-count").textContent = total;
  $("#blocked-count").textContent = blocked;
  $("#decision-title").textContent = report.can_start ? "Collection can start." : "Collection is fail-closed.";
  $("#decision-copy").textContent = report.can_start ? "Every factor is ready and the run manifest can be prepared." : "Preflight evidence is visible here. No benchmark run is counted until every factor passes the readiness gate.";
  $("#decision-status").textContent = report.can_start ? "Pilot ready" : "Pilot blocked";
  $("#dataset-label").textContent = `preflight-${report.protocol_version || "v1.1"}`;
  renderComponents(preflight);
  renderConditions(report);
}

function metricValue(results, field, formatter = (value) => value.toFixed(2)) {
  const value = results.metrics?.[field]?.median;
  return typeof value === "number" ? formatter(value) : "—";
}

function renderResults(results) {
  const noResults = results.status === "no-results" || !results.summary?.runs;
  const cards = [
    ["Runs", results.summary?.runs ?? 0, "versioned bundles"],
    ["Evaluated", results.summary?.evaluated_runs ?? 0, "blind evaluator records"],
    ["Technical pilots", results.summary?.excluded_runs ?? 0, "excluded from official analysis"],
    ["Effective work", metricValue(results, "effective_work_hours", (value) => `${value.toFixed(2)} h`), "median per run"],
    ["Speedup", metricValue(results, "speedup_vs_baseline", (value) => `${value.toFixed(2)}×`), "vs Senior Engineer baseline"],
    ["Quality", metricValue(results, "quality_score", (value) => `${value.toFixed(1)}/100`), "median product score"],
  ];
  $("#results-grid").innerHTML = cards.map(([title, value, detail]) => `<article class="result-card${noResults ? " result-empty" : ""}"><span>${title}</span><strong>${value}</strong><small>${detail}</small></article>`).join("");
  $("#results-note").textContent = noResults
    ? `${results.summary?.excluded_runs ?? 0} technical pilot(s) are tracked separately. No official performance result exists yet.`
    : `${results.summary.runs} run bundles are available in processed dataset ${results.schema_version}.`
  $("#results-caption").textContent = noResults
    ? "No performance number is published before a valid run bundle and evaluator record exist."
    : "Results are generated from append-only ledgers and versioned evaluator records."
}

function renderExecutionReadiness(execution) {
  const summary = execution.blocker_summary || {};
  $("#upstream-count").textContent = summary.upstream ?? 0;
  $("#operator-count").textContent = summary.operator ?? 0;
  $("#protocol-count").textContent = summary.protocol ?? 0;
  $("#technical-ready-count").textContent = execution.technical_conditions_ready?.length ?? 0;
  const blockers = execution.blockers || [];
  $("#blocker-empty").hidden = blockers.length > 0;
  $("#blocker-list").innerHTML = blockers.map((blocker) => `
    <article class="blocker-card">
      <div class="blocker-card-topline">
        <span>${label(blocker.component.replace(":", " / "))}</span>
        <span class="owner owner-${blocker.owner}">${blocker.owner}</span>
      </div>
      <h3>${label(blocker.blocker_id)}</h3>
      <p>${blocker.reason}</p>
      <details>
        <summary>Recovery evidence</summary>
        <p>${blocker.next_action}</p>
        <code>${blocker.recheck_command}</code>
        <a class="source-link" href="../${blocker.evidence_ref}">Open evidence <span aria-hidden="true">↗</span></a>
      </details>
    </article>`).join("");
}

const [preflight, report, results, execution] = await Promise.all([
  loadJson(SOURCES.preflight, "preflight"),
  loadJson(SOURCES.readiness, "readiness"),
  loadJson(SOURCES.results, "results"),
  loadJson(SOURCES.execution, "execution"),
]);

renderReadiness(preflight, report);
renderResults(results);
renderExecutionReadiness(execution);
$("#ade-filter").addEventListener("change", (event) => renderConditions(report, event.target.value));
