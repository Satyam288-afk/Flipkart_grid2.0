import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock3,
  Download,
  FileText,
  MapPin,
  RadioTower,
  Route,
  ShieldCheck,
  Siren,
  Users,
} from "lucide-react";
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const demoScenarios = [
  {
    name: "VIP movement",
    event_type: "planned",
    event_cause: "vip_movement",
    latitude: 12.9791,
    longitude: 77.5913,
    start_datetime: "2024-04-08T14:30:00+05:30",
    corridor: "Non-corridor",
    police_station: "Cubbon Park",
    zone: "Central Zone 2",
    junction: "VidhanaSoudhaJunction",
    description: "VIP movement with temporary blockade near central business area",
    operating_mode: "balanced",
  },
  {
    name: "Public event",
    event_type: "planned",
    event_cause: "public_event",
    latitude: 12.9719,
    longitude: 77.6412,
    start_datetime: "2024-04-08T18:00:00+05:30",
    corridor: "ORR East 1",
    police_station: "Indiranagar",
    zone: "East Zone",
    junction: "IndiranagarJunction",
    description: "Large public event crowd expected near junction and feeder roads",
    operating_mode: "balanced",
  },
  {
    name: "Tree fall",
    event_type: "unplanned",
    event_cause: "tree_fall",
    latitude: 13.0061,
    longitude: 77.5794,
    start_datetime: "2024-04-08T08:15:00+05:30",
    corridor: "Non-corridor",
    police_station: "Sadashivanagar",
    zone: "Central Zone",
    junction: "BashyamCircle",
    description: "Tree fall blocking one lane after heavy rain",
    operating_mode: "balanced",
  },
  {
    name: "Vehicle breakdown",
    event_type: "unplanned",
    event_cause: "vehicle_breakdown",
    latitude: 12.9219,
    longitude: 77.6452,
    start_datetime: "2024-04-08T09:20:00+05:30",
    corridor: "ORR East 1",
    police_station: "HSR Layout",
    zone: "South East Zone",
    junction: "AgaraJunction",
    description: "Heavy vehicle breakdown near main carriageway",
    operating_mode: "balanced",
  },
];

const views = [
  { id: "command", label: "Command Center", icon: Siren },
  { id: "simulator", label: "Simulator", icon: BarChart3 },
  { id: "live", label: "Live Ops", icon: RadioTower },
  { id: "model", label: "Model", icon: ShieldCheck },
  { id: "reports", label: "Reports", icon: FileText },
];

function levelColor(level) {
  if (level === "Critical") return "#ef4444";
  if (level === "High") return "#f97316";
  if (level === "Medium") return "#eab308";
  return "#22c55e";
}

function formatPercent(value) {
  return `${Math.round((value || 0) * 100)}%`;
}

function titleCase(value) {
  return String(value || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function Field({ label, value, onChange, type = "text", options }) {
  if (options) {
    return (
      <label className="field">
        <span>{label}</span>
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          {options.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
      </label>
    );
  }
  return (
    <label className="field">
      <span>{label}</span>
      <input value={value} type={type} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function MetricCard({ icon: Icon, label, value, detail, tone = "default" }) {
  return (
    <section className={`metric-card metric-${tone}`}>
      <div className="metric-icon"><Icon size={18} /></div>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        <span>{detail}</span>
      </div>
    </section>
  );
}

function RiskMap({ form, result, hotspots }) {
  const color = levelColor(result?.risk_level);
  const center = [Number(form.latitude) || 12.9716, Number(form.longitude) || 77.5946];
  const corridorLine = [center, [center[0] + 0.012, center[1] + 0.018], [center[0] + 0.019, center[1] - 0.007]];

  return (
    <MapContainer center={center} zoom={12} scrollWheelZoom className="map">
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {result && <Polyline positions={corridorLine} pathOptions={{ color, weight: 5, opacity: 0.62 }} />}
      <CircleMarker center={center} radius={15} pathOptions={{ color, fillColor: color, fillOpacity: 0.78 }}>
        <Popup><strong>{titleCase(form.event_cause)}</strong><br />{result ? `${result.risk_level} risk, score ${result.impact_score}` : "Awaiting impact prediction"}</Popup>
      </CircleMarker>
      {hotspots.slice(0, 18).map((spot, index) => spot.latitude && spot.longitude ? (
        <CircleMarker key={`${spot.event_cause}-${spot.corridor}-${index}`} center={[spot.latitude, spot.longitude]} radius={5 + Math.min(11, spot.hotspot_score * 11)} pathOptions={{ color: "#14b8a6", fillColor: "#14b8a6", fillOpacity: 0.32 }}>
          <Popup><strong>{titleCase(spot.event_cause)}</strong><br />{spot.corridor}<br />Closure rate: {spot.closure_rate}</Popup>
        </CircleMarker>
      ) : null)}
    </MapContainer>
  );
}

function TabNav({ activeView, setActiveView }) {
  return (
    <nav className="view-nav" aria-label="EventGrid sections">
      {views.map(({ id, label, icon: Icon }) => (
        <button className={activeView === id ? "active" : ""} key={id} type="button" onClick={() => setActiveView(id)}>
          <Icon size={17} />
          {label}
        </button>
      ))}
    </nav>
  );
}

function EmptyHint({ children }) {
  return <div className="empty-state">{children}</div>;
}

function EventIntake({ form, setForm, update, predict, loading, error }) {
  return (
    <form className="panel input-panel" onSubmit={predict}>
      <div className="section-heading"><MapPin size={19} /><h2>Event intake</h2></div>
      <div className="demo-row">
        {demoScenarios.map((scenario) => <button type="button" key={scenario.name} onClick={() => setForm(scenario)}>{scenario.name}</button>)}
      </div>
      <div className="form-grid">
        <Field label="Event type" value={form.event_type} options={["planned", "unplanned"]} onChange={(value) => update("event_type", value)} />
        <Field label="Event cause" value={form.event_cause} options={["vip_movement", "procession", "public_event", "tree_fall", "water_logging", "vehicle_breakdown", "construction", "accident", "congestion", "others"]} onChange={(value) => update("event_cause", value)} />
        <Field label="Operating mode" value={form.operating_mode || "balanced"} options={["balanced", "high_recall", "high_precision"]} onChange={(value) => update("operating_mode", value)} />
        <Field label="Latitude" value={form.latitude} type="number" onChange={(value) => update("latitude", value)} />
        <Field label="Longitude" value={form.longitude} type="number" onChange={(value) => update("longitude", value)} />
        <Field label="Start datetime" value={form.start_datetime} onChange={(value) => update("start_datetime", value)} />
        <Field label="Corridor" value={form.corridor} onChange={(value) => update("corridor", value)} />
        <Field label="Police station" value={form.police_station} onChange={(value) => update("police_station", value)} />
        <Field label="Zone" value={form.zone} onChange={(value) => update("zone", value)} />
        <Field label="Junction" value={form.junction} onChange={(value) => update("junction", value)} />
      </div>
      <label className="field description-field">
        <span>Description</span>
        <textarea value={form.description} onChange={(event) => update("description", event.target.value)} rows={4} />
      </label>
      <button className="primary-button" type="submit" disabled={loading}>{loading ? "Running impact model..." : "Predict impact"}</button>
      {error && <p className="error">{error}</p>}
    </form>
  );
}

function OperationalDecision({ form, result, scoreStyle }) {
  return (
    <aside className="panel command-summary">
      <div className="section-heading"><Siren size={19} /><h2>Operational decision</h2></div>
      {result ? (
        <>
          <div className="score-row vertical">
            <div className="score-ring" style={scoreStyle}><div><strong>{result.impact_score}</strong><span>{result.risk_level}</span></div></div>
            <div className="score-copy centered"><h3>{result.risk_level} impact</h3><p>{titleCase(form.event_cause)} at {titleCase(form.junction || form.corridor)}</p></div>
          </div>
          <div className="decision-grid">
            <MetricCard icon={Users} label="Manpower" value={result.recommended_manpower} detail={titleCase(result.response_team_type)} tone="strong" />
            <MetricCard icon={Route} label="Diversion" value={titleCase(result.diversion_plan?.diversion_type || (result.diversion_required ? "activate" : "standby"))} detail={result.diversion_plan?.affected_corridor || form.corridor} tone={result.diversion_required ? "danger" : "default"} />
            <MetricCard icon={CheckCircle2} label="Barricading" value={result.barricading_required ? "Required" : "No"} detail={result.barricading_required ? "Temporary lane control" : "Monitor only"} />
          </div>
        </>
      ) : <EmptyHint>Select a scenario and run prediction.</EmptyHint>}
    </aside>
  );
}

function RiskSignals({ result }) {
  return (
    <section className="panel result-panel">
      <div className="section-heading"><AlertTriangle size={19} /><h2>Risk signals</h2></div>
      {result ? (
        <>
          <div className="metric-grid">
            <MetricCard icon={AlertTriangle} label="Closure probability" value={formatPercent(result.road_closure_probability)} detail="Primary model target" />
            <MetricCard icon={ShieldCheck} label="Closure decision" value={result.closure_decision?.closure_flag ? "Flagged" : "Below threshold"} detail={`${titleCase(result.closure_decision?.operating_mode)} at ${formatPercent(result.closure_decision?.threshold)}`} />
            <MetricCard icon={BarChart3} label="High priority probability" value={formatPercent(result.high_priority_probability)} detail="Secondary severity signal" />
            <MetricCard icon={RadioTower} label="Hotspot score" value={formatPercent(result.historical_hotspot_score)} detail="Cause, corridor, station, geobin" />
            <MetricCard icon={Clock3} label="Expected duration" value={`${result.expected_duration_hours}h`} detail="Cleaned operational timestamp estimate" />
            <MetricCard icon={ShieldCheck} label="Confidence" value={result.prediction_confidence?.confidence_level || "NA"} detail={`${result.prediction_confidence?.confidence_score ?? 0}/100 data coverage`} />
          </div>
          <section className="recommendation"><h3>Recommendation rationale</h3><ul>{result.explanation.map((item) => <li key={item}>{item}</li>)}</ul></section>
        </>
      ) : <EmptyHint>Prediction output appears here after the impact model runs.</EmptyHint>}
    </section>
  );
}

function ScoreBreakdown({ result }) {
  if (!result?.score_components) return <EmptyHint>Run a prediction to inspect weighted score components.</EmptyHint>;
  return (
    <section className="panel explain-panel">
      <div className="section-heading"><BarChart3 size={19} /><h2>Impact score breakdown</h2></div>
      <div className="component-list">
        {result.score_components.map((component) => (
          <div className="component-row" key={component.name}>
            <div className="component-label"><strong>{component.name}</strong><span>{Math.round(component.weight * 100)}% weight</span></div>
            <div className="component-bar"><div style={{ width: `${Math.min(100, component.value * 100)}%` }} /></div>
            <div className="component-points">{component.weighted_points}</div>
            <p>{component.reason}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function TopFactors({ result }) {
  if (!result?.top_prediction_factors?.length) return <EmptyHint>Top factors appear after prediction.</EmptyHint>;
  return (
    <section className="panel factors-panel">
      <div className="section-heading"><ShieldCheck size={19} /><h2>Top factors</h2></div>
      <div className="factor-list">
        {result.top_prediction_factors.map((factor) => (
          <article className="factor-card" key={`${factor.factor}-${factor.evidence}`}><div><strong>{factor.factor}</strong><span>{factor.direction}</span></div><b>{factor.strength}</b><p>{factor.evidence}</p></article>
        ))}
      </div>
    </section>
  );
}

function DiversionPlan({ result }) {
  const plan = result?.diversion_plan;
  if (!plan) return <EmptyHint>Diversion guidance appears after prediction.</EmptyHint>;
  return (
    <section className="panel diversion-panel">
      <div className="section-heading"><Route size={19} /><h2>Diversion plan</h2></div>
      <div className="diversion-status"><strong>{titleCase(plan.diversion_type)}</strong><span>{plan.affected_corridor}</span></div>
      <p className="panel-copy">{plan.strategy}</p>
      <div className="control-points">{plan.control_points.map((point) => <span key={point}>{point}</span>)}</div>
      <p className="operator-note">{plan.operator_note}</p>
    </section>
  );
}

function ActionTimeline({ result }) {
  if (!result?.action_timeline) return <EmptyHint>Deployment timeline appears after prediction.</EmptyHint>;
  return (
    <section className="panel timeline-panel">
      <div className="section-heading"><Clock3 size={19} /><h2>Deployment timeline</h2></div>
      <div className="timeline">
        {result.action_timeline.map((step) => (
          <article className="timeline-step" key={`${step.offset_minutes}-${step.title}`}><div className="timeline-time">T+{step.offset_minutes}</div><div><h3>{step.title}</h3><p>{step.action}</p><span>{titleCase(step.owner)}</span></div></article>
        ))}
      </div>
    </section>
  );
}

function SimilarEvidence({ result }) {
  const evidence = result?.similar_event_evidence;
  if (!evidence) return <EmptyHint>Historical evidence appears after prediction.</EmptyHint>;
  return (
    <section className="panel evidence-panel">
      <div className="section-heading"><ShieldCheck size={19} /><h2>Historical evidence</h2></div>
      <div className="evidence-grid">
        <MetricCard icon={RadioTower} label="Similar cases" value={evidence.sample_size} detail="Nearest cause/location matches" />
        <MetricCard icon={AlertTriangle} label="Past closure ratio" value={`${evidence.closure_count}/${evidence.sample_size}`} detail={`${formatPercent(evidence.closure_rate)} closure rate`} />
        <MetricCard icon={BarChart3} label="High priority cases" value={evidence.high_priority_count} detail="Within selected similar events" />
        <MetricCard icon={Clock3} label="Avg duration" value={evidence.average_duration_hours ?? "NA"} detail="Hours from valid resolved records" />
      </div>
    </section>
  );
}

function SimilarEventsPanel({ result }) {
  return (
    <section className="panel">
      <div className="section-heading"><Route size={19} /><h2>Similar past events</h2></div>
      {result?.similar_past_events?.length ? (
        <div className="table-wrap"><table><thead><tr><th>Cause</th><th>Corridor</th><th>Priority</th><th>Closure</th><th>Duration</th></tr></thead><tbody>
          {result.similar_past_events.map((event) => <tr key={event.id}><td>{titleCase(event.event_cause)}</td><td>{event.corridor}</td><td>{titleCase(event.priority)}</td><td>{event.requires_road_closure ? "Yes" : "No"}</td><td>{event.duration_hours ?? "NA"}</td></tr>)}
        </tbody></table></div>
      ) : <EmptyHint>Similar events appear after a prediction.</EmptyHint>}
    </section>
  );
}

function HotspotsPanel({ hotspots }) {
  return (
    <section className="panel">
      <div className="section-heading"><AlertTriangle size={19} /><h2>Historical hotspots</h2></div>
      <div className="table-wrap compact"><table><thead><tr><th>Cause</th><th>Police station</th><th>Events</th><th>Closure rate</th></tr></thead><tbody>
        {hotspots.slice(0, 8).map((spot, index) => <tr key={`${spot.event_cause}-${spot.police_station}-${index}`}><td>{titleCase(spot.event_cause)}</td><td>{titleCase(spot.police_station)}</td><td>{spot.event_count}</td><td>{spot.closure_rate}</td></tr>)}
      </tbody></table></div>
    </section>
  );
}

function IncidentReport({ result, form }) {
  if (!result?.incident_report) return <EmptyHint>Generate a prediction to export an incident report.</EmptyHint>;
  function exportReport() {
    const payload = { ...result.incident_report, current_event_form: form, explanation: result.explanation, similar_past_events: result.similar_past_events, action_timeline: result.action_timeline, diversion_plan: result.diversion_plan };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${result.incident_report.report_id}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <section className="panel report-panel">
      <div className="section-heading"><Download size={19} /><h2>Incident report</h2></div>
      <div className="report-card"><div><span>Report ID</span><strong>{result.incident_report.report_id}</strong></div><div><span>Generated</span><strong>{new Date(result.generated_at).toLocaleString()}</strong></div></div>
      <button className="secondary-button" type="button" onClick={exportReport}><Download size={17} />Export report JSON</button>
    </section>
  );
}

function makeWhatIfPayloads(form) {
  const start = new Date(form.start_datetime || Date.now());
  const peak = new Date(start); peak.setHours(18, 30, 0, 0);
  const late = new Date(start); late.setHours(23, 0, 0, 0);
  const alternateCause = form.event_cause === "vehicle_breakdown" ? "procession" : "vehicle_breakdown";
  return [
    { label: "Current plan", description: "Original field report", payload: form },
    { label: "Peak-hour replay", description: "Same event during evening peak", payload: { ...form, start_datetime: peak.toISOString() } },
    { label: "Late-night replay", description: "Same event during low-demand window", payload: { ...form, start_datetime: late.toISOString() } },
    { label: titleCase(alternateCause), description: "Same location with a different event cause", payload: { ...form, event_cause: alternateCause, description: `${titleCase(alternateCause)} scenario at ${form.junction || form.corridor}` } },
  ];
}

function WhatIfSimulator({ form, onRun, results, loading }) {
  return (
    <section className="panel whatif-panel">
      <div className="section-heading"><BarChart3 size={19} /><h2>What-if simulator</h2></div>
      <p className="panel-copy">Replay the current event through the same model under alternate time/cause assumptions before deployment.</p>
      <button className="secondary-button" type="button" onClick={onRun} disabled={loading}><BarChart3 size={17} />{loading ? "Running scenarios..." : "Run what-if comparison"}</button>
      {results.length > 0 && <div className="whatif-grid">{results.map((item) => <article className="whatif-card" key={item.label}><div><strong>{item.label}</strong><span>{item.description}</span></div><b style={{ color: levelColor(item.result.risk_level) }}>{item.result.impact_score}</b><p>{item.result.risk_level} risk</p><small>{item.result.recommended_manpower} officers, {titleCase(item.result.diversion_plan.diversion_type)}</small></article>)}</div>}
    </section>
  );
}

function ArchitecturePanel() {
  const steps = ["CSV events", "Cleaning", "Feature store", "CatBoost models", "Impact score", "Recommendations", "FastAPI", "Command UI"];
  return <section className="panel architecture-panel"><div className="section-heading"><RadioTower size={19} /><h2>System architecture</h2></div><div className="architecture-flow">{steps.map((step) => <div className="architecture-step" key={step}>{step}</div>)}</div></section>;
}

function UsersImpactPanel() {
  return (
    <section className="panel users-panel">
      <div className="section-heading"><Users size={19} /><h2>Users and impact</h2></div>
      <div className="impact-grid"><article><strong>Traffic police control room</strong><span>Earlier triage, deployment sizing, and closure readiness.</span></article><article><strong>Field officers</strong><span>Clear action timeline and junction-level control points.</span></article><article><strong>Smart city teams</strong><span>Repeatable event-learning loop from historical operations records.</span></article></div>
    </section>
  );
}

function LiveOperationsPanel({ liveEvents, systemSummary, onSave, onSimulate, onReview, loading, hasResult }) {
  const operations = systemSummary?.operations;
  return (
    <section className="panel live-panel">
      <div className="section-heading"><RadioTower size={19} /><h2>Live operations and approvals</h2></div>
      <div className="ops-grid">
        <MetricCard icon={RadioTower} label="Live events" value={operations?.live_events_total ?? liveEvents.length} detail="Persisted in SQLite" />
        <MetricCard icon={Clock3} label="Pending approvals" value={operations?.pending_approvals ?? 0} detail="Human-in-the-loop queue" />
        <MetricCard icon={ShieldCheck} label="Auth mode" value={systemSummary?.auth_mode || "demo"} detail="Set EVENTGRID_API_KEY for API-key mode" />
        <MetricCard icon={AlertTriangle} label="High/Critical" value={operations?.high_or_critical_events ?? 0} detail="Operational monitoring signal" />
      </div>
      <div className="ops-actions"><button className="secondary-button" type="button" onClick={onSave} disabled={loading || !hasResult}><Download size={17} />Persist current event</button><button className="secondary-button" type="button" onClick={onSimulate} disabled={loading}><RadioTower size={17} />Simulate live feed</button></div>
      <div className="live-list">
        {liveEvents.slice(0, 8).map((event) => <article className="live-card" key={event.id}><div><strong>#{event.id} {titleCase(event.event.event_cause)}</strong><span>{event.risk_level} risk, score {event.impact_score}</span></div><b className={`approval-badge approval-${event.approval_status}`}>{titleCase(event.approval_status)}</b><p>{event.prediction.diversion_plan?.strategy}</p><div className="approval-actions"><button type="button" onClick={() => onReview(event.id, "approved")} disabled={loading || event.approval_status === "approved"}>Approve</button><button type="button" onClick={() => onReview(event.id, "rejected")} disabled={loading || event.approval_status === "rejected"}>Reject</button></div></article>)}
        {liveEvents.length === 0 && <EmptyHint>Persist a prediction or simulate a live feed to populate the operator approval queue.</EmptyHint>}
      </div>
    </section>
  );
}

function MetricsPanel({ metrics }) {
  const strategy = metrics?.road_closure_serving_strategy;
  const operating = metrics?.road_closure_operating_metrics;
  return (
    <section className="panel metrics-panel">
      <div className="section-heading"><BarChart3 size={19} /><h2>Model metrics</h2></div>
      {metrics ? <div className="metrics-list"><span>Train rows: {metrics.train_rows}</span><span>Test rows: {metrics.test_rows}</span><span>ROC-AUC: {metrics.road_closure_model?.roc_auc?.toFixed(3)}</span><span>PR-AUC: {metrics.road_closure_model?.average_precision?.toFixed(3)}</span><span>Top 10% capture: {metrics.road_closure_model?.top_10_percent_risk_capture_rate?.toFixed(3)}</span><span>Operating F1: {operating?.f1?.toFixed(3)}</span><span>Serving mode: {strategy?.probability_mode || "raw"}</span><span>Duration MAE: {metrics.duration_model?.mae_hours?.toFixed(2)}h</span></div> : <EmptyHint>Metrics load when the API is running.</EmptyHint>}
    </section>
  );
}

function ModelDiagnosticsPanel({ metrics }) {
  const points = metrics?.operating_points || {};
  const balanced = points.balanced || { threshold: 0.75, precision: 0.427, recall: 0.472 };
  const highRecall = points.high_recall || { threshold: 0.35, recall: 0.775 };
  const highPrecision = points.high_precision || { threshold: 0.85, precision: 0.436 };
  const strategy = metrics?.road_closure_serving_strategy;
  return (
    <section className="panel model-diagnostics-panel">
      <div className="section-heading"><ShieldCheck size={19} /><h2>Operating thresholds</h2></div>
      <div className="threshold-grid">
        <MetricCard icon={BarChart3} label="Balanced F1" value={balanced.threshold} detail={`Precision ${balanced.precision}, recall ${balanced.recall}`} />
        <MetricCard icon={AlertTriangle} label="High recall" value={highRecall.threshold} detail={`Recall ${highRecall.recall} for operations mode`} />
        <MetricCard icon={ShieldCheck} label="High precision" value={highPrecision.threshold} detail={`Precision ${highPrecision.precision} for review mode`} />
      </div>
      <p className="operator-note">Thresholds come from reports/model_diagnostics.json. Serving mode: {strategy?.probability_mode || "raw"} probability. The product uses probability continuously for impact scoring.</p>
    </section>
  );
}

function CurrentEventCard({ form, result }) {
  return <section className="panel context-panel"><div className="section-heading"><MapPin size={19} /><h2>Current event context</h2></div><div className="context-grid"><span>Cause: <b>{titleCase(form.event_cause)}</b></span><span>Corridor: <b>{form.corridor}</b></span><span>Junction: <b>{form.junction}</b></span><span>Station: <b>{form.police_station}</b></span>{result && <span>Last score: <b>{result.impact_score} {result.risk_level}</b></span>}</div></section>;
}

function App() {
  const [activeView, setActiveView] = useState("command");
  const [form, setForm] = useState(demoScenarios[0]);
  const [result, setResult] = useState(null);
  const [hotspots, setHotspots] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [systemSummary, setSystemSummary] = useState(null);
  const [liveEvents, setLiveEvents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [whatIfLoading, setWhatIfLoading] = useState(false);
  const [liveLoading, setLiveLoading] = useState(false);
  const [whatIfResults, setWhatIfResults] = useState([]);
  const [error, setError] = useState("");

  async function refreshOperations() {
    const [eventsResponse, summaryResponse] = await Promise.all([fetch(`${API_BASE}/live-events`), fetch(`${API_BASE}/monitoring/summary`)]);
    if (eventsResponse.ok) setLiveEvents((await eventsResponse.json()).live_events || []);
    if (summaryResponse.ok) setSystemSummary(await summaryResponse.json());
  }

  useEffect(() => {
    fetch(`${API_BASE}/hotspots`).then((response) => response.json()).then((payload) => setHotspots(payload.hotspots || [])).catch(() => setHotspots([]));
    fetch(`${API_BASE}/model-metrics`).then((response) => response.json()).then(setMetrics).catch(() => setMetrics(null));
    refreshOperations().catch(() => {});
  }, []);

  const scoreStyle = useMemo(() => ({ background: `conic-gradient(${levelColor(result?.risk_level)} ${(result?.impact_score || 0) * 3.6}deg, #202938 0deg)` }), [result]);
  function update(name, value) { setForm((current) => ({ ...current, [name]: value })); }

  async function predict(event) {
    event.preventDefault(); setLoading(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/predict-impact`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...form, latitude: Number(form.latitude), longitude: Number(form.longitude) }) });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      setResult(await response.json());
      setActiveView("command");
    } catch (err) { setError(err.message || "Prediction failed"); } finally { setLoading(false); }
  }

  async function runWhatIf() {
    setWhatIfLoading(true); setError("");
    try {
      const responses = await Promise.all(makeWhatIfPayloads(form).map(async (scenario) => {
        const response = await fetch(`${API_BASE}/predict-impact`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...scenario.payload, latitude: Number(scenario.payload.latitude), longitude: Number(scenario.payload.longitude) }) });
        if (!response.ok) throw new Error(`What-if API returned ${response.status}`);
        return { ...scenario, result: await response.json() };
      }));
      setWhatIfResults(responses);
    } catch (err) { setError(err.message || "What-if simulation failed"); } finally { setWhatIfLoading(false); }
  }

  async function saveCurrentEvent() {
    setLiveLoading(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/live-events?source=operator_dashboard`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...form, latitude: Number(form.latitude), longitude: Number(form.longitude) }) });
      if (!response.ok) throw new Error(`Live event API returned ${response.status}`);
      await refreshOperations(); setActiveView("live");
    } catch (err) { setError(err.message || "Live event save failed"); } finally { setLiveLoading(false); }
  }

  async function simulateLiveFeed() {
    setLiveLoading(true); setError("");
    try { const response = await fetch(`${API_BASE}/simulate-live-feed`, { method: "POST" }); if (!response.ok) throw new Error(`Simulated feed API returned ${response.status}`); await refreshOperations(); }
    catch (err) { setError(err.message || "Simulated feed failed"); } finally { setLiveLoading(false); }
  }

  async function reviewLiveEvent(id, status) {
    setLiveLoading(true); setError("");
    try {
      const response = await fetch(`${API_BASE}/live-events/${id}/approval`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, reviewer: "control_room_operator", note: status === "approved" ? "Approved from command dashboard" : "Rejected from command dashboard" }) });
      if (!response.ok) throw new Error(`Approval API returned ${response.status}`);
      await refreshOperations();
    } catch (err) { setError(err.message || "Approval update failed"); } finally { setLiveLoading(false); }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div><h1>EventGrid AI</h1><p className="subtitle">Traffic incident command center for event-driven operational impact, manpower, barricading, and diversion planning.</p></div>
        <div className="status-stack"><div className="status-pill"><ShieldCheck size={17} />Dataset-backed ML</div><div className="status-pill muted"><RadioTower size={17} />{metrics ? `${metrics.train_rows + metrics.test_rows} events learned` : "Loading model"}</div></div>
      </header>
      <TabNav activeView={activeView} setActiveView={setActiveView} />

      {activeView === "command" && <section className="view-panel"><section className="command-grid"><section className="panel command-map-panel"><div className="map-header"><div className="section-heading"><MapPin size={19} /><h2>Live operational map</h2></div><div className="map-legend"><span><i className="green" /> Low</span><span><i className="yellow" /> Medium</span><span><i className="orange" /> High</span><span><i className="red" /> Critical</span></div></div><RiskMap form={form} result={result} hotspots={hotspots} /></section><OperationalDecision form={form} result={result} scoreStyle={scoreStyle} /></section><section className="workspace-grid"><EventIntake form={form} setForm={setForm} update={update} predict={predict} loading={loading} error={error} /><RiskSignals result={result} /><ScoreBreakdown result={result} /><TopFactors result={result} /><DiversionPlan result={result} /></section></section>}

      {activeView === "simulator" && <section className="view-panel workspace-grid"><CurrentEventCard form={form} result={result} /><WhatIfSimulator form={form} onRun={runWhatIf} results={whatIfResults} loading={whatIfLoading} /><ActionTimeline result={result} /><SimilarEvidence result={result} /></section>}

      {activeView === "live" && <section className="view-panel workspace-grid"><LiveOperationsPanel liveEvents={liveEvents} systemSummary={systemSummary} onSave={saveCurrentEvent} onSimulate={simulateLiveFeed} onReview={reviewLiveEvent} loading={liveLoading} hasResult={Boolean(result)} /><HotspotsPanel hotspots={hotspots} /></section>}

      {activeView === "model" && <section className="view-panel workspace-grid"><MetricsPanel metrics={metrics} /><ModelDiagnosticsPanel metrics={metrics} /><ArchitecturePanel /><UsersImpactPanel /></section>}

      {activeView === "reports" && <section className="view-panel workspace-grid"><IncidentReport result={result} form={form} /><SimilarEventsPanel result={result} /><SimilarEvidence result={result} /><LiveOperationsPanel liveEvents={liveEvents} systemSummary={systemSummary} onSave={saveCurrentEvent} onSimulate={simulateLiveFeed} onReview={reviewLiveEvent} loading={liveLoading} hasResult={Boolean(result)} /></section>}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
