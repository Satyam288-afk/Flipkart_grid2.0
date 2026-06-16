import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock3,
  Download,
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
  },
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
            <option key={option} value={option}>
              {option}
            </option>
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
      <div className="metric-icon">
        <Icon size={18} />
      </div>
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
  const corridorLine = [
    center,
    [center[0] + 0.012, center[1] + 0.018],
    [center[0] + 0.019, center[1] - 0.007],
  ];

  return (
    <MapContainer center={center} zoom={12} scrollWheelZoom className="map">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {result && <Polyline positions={corridorLine} pathOptions={{ color, weight: 5, opacity: 0.62 }} />}
      <CircleMarker center={center} radius={15} pathOptions={{ color, fillColor: color, fillOpacity: 0.78 }}>
        <Popup>
          <strong>{titleCase(form.event_cause)}</strong>
          <br />
          {result ? `${result.risk_level} risk, score ${result.impact_score}` : "Awaiting impact prediction"}
        </Popup>
      </CircleMarker>
      {hotspots.slice(0, 18).map((spot, index) => {
        if (!spot.latitude || !spot.longitude) return null;
        return (
          <CircleMarker
            key={`${spot.event_cause}-${spot.corridor}-${index}`}
            center={[spot.latitude, spot.longitude]}
            radius={5 + Math.min(11, spot.hotspot_score * 11)}
            pathOptions={{ color: "#14b8a6", fillColor: "#14b8a6", fillOpacity: 0.32 }}
          >
            <Popup>
              <strong>{titleCase(spot.event_cause)}</strong>
              <br />
              {spot.corridor}
              <br />
              Closure rate: {spot.closure_rate}
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}

function ScoreBreakdown({ result }) {
  if (!result?.score_components) return null;
  return (
    <section className="panel explain-panel">
      <div className="section-heading">
        <BarChart3 size={19} />
        <h2>Impact score breakdown</h2>
      </div>
      <div className="component-list">
        {result.score_components.map((component) => (
          <div className="component-row" key={component.name}>
            <div className="component-label">
              <strong>{component.name}</strong>
              <span>{Math.round(component.weight * 100)}% weight</span>
            </div>
            <div className="component-bar">
              <div style={{ width: `${Math.min(100, component.value * 100)}%` }} />
            </div>
            <div className="component-points">{component.weighted_points}</div>
            <p>{component.reason}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function ActionTimeline({ result }) {
  if (!result?.action_timeline) return null;
  return (
    <section className="panel timeline-panel">
      <div className="section-heading">
        <Clock3 size={19} />
        <h2>Deployment timeline</h2>
      </div>
      <div className="timeline">
        {result.action_timeline.map((step) => (
          <article className="timeline-step" key={`${step.offset_minutes}-${step.title}`}>
            <div className="timeline-time">T+{step.offset_minutes}</div>
            <div>
              <h3>{step.title}</h3>
              <p>{step.action}</p>
              <span>{titleCase(step.owner)}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function SimilarEvidence({ result }) {
  const evidence = result?.similar_event_evidence;
  if (!evidence) return null;
  return (
    <section className="panel evidence-panel">
      <div className="section-heading">
        <ShieldCheck size={19} />
        <h2>Historical evidence</h2>
      </div>
      <div className="evidence-grid">
        <MetricCard icon={RadioTower} label="Similar cases" value={evidence.sample_size} detail="Nearest cause/location matches" />
        <MetricCard icon={AlertTriangle} label="Past closure ratio" value={`${evidence.closure_count}/${evidence.sample_size}`} detail={`${formatPercent(evidence.closure_rate)} closure rate`} />
        <MetricCard icon={BarChart3} label="High priority cases" value={evidence.high_priority_count} detail="Within selected similar events" />
        <MetricCard icon={Clock3} label="Avg duration" value={evidence.average_duration_hours ?? "NA"} detail="Hours from valid resolved records" />
      </div>
    </section>
  );
}

function IncidentReport({ result, form }) {
  if (!result?.incident_report) return null;

  function exportReport() {
    const payload = {
      ...result.incident_report,
      current_event_form: form,
      explanation: result.explanation,
      similar_past_events: result.similar_past_events,
      action_timeline: result.action_timeline,
    };
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
      <div className="section-heading">
        <Download size={19} />
        <h2>Incident report</h2>
      </div>
      <div className="report-card">
        <div>
          <span>Report ID</span>
          <strong>{result.incident_report.report_id}</strong>
        </div>
        <div>
          <span>Generated</span>
          <strong>{new Date(result.generated_at).toLocaleString()}</strong>
        </div>
      </div>
      <button className="secondary-button" type="button" onClick={exportReport}>
        <Download size={17} />
        Export report JSON
      </button>
    </section>
  );
}

function App() {
  const [form, setForm] = useState(demoScenarios[0]);
  const [result, setResult] = useState(null);
  const [hotspots, setHotspots] = useState([]);
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/hotspots`)
      .then((response) => response.json())
      .then((payload) => setHotspots(payload.hotspots || []))
      .catch(() => setHotspots([]));
    fetch(`${API_BASE}/model-metrics`)
      .then((response) => response.json())
      .then(setMetrics)
      .catch(() => setMetrics(null));
  }, []);

  const scoreStyle = useMemo(() => {
    const score = result?.impact_score || 0;
    return { background: `conic-gradient(${levelColor(result?.risk_level)} ${score * 3.6}deg, #202938 0deg)` };
  }, [result]);

  function update(name, value) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  async function predict(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/predict-impact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          latitude: Number(form.latitude),
          longitude: Number(form.longitude),
        }),
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      setResult(await response.json());
    } catch (err) {
      setError(err.message || "Prediction failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Flipkart Gridlock Hackathon 2.0</p>
          <h1>EventGrid AI</h1>
          <p className="subtitle">Traffic incident command center for event-driven operational impact, manpower, barricading, and diversion planning.</p>
        </div>
        <div className="status-stack">
          <div className="status-pill">
            <ShieldCheck size={17} />
            Dataset-backed ML
          </div>
          <div className="status-pill muted">
            <RadioTower size={17} />
            {metrics ? `${metrics.train_rows + metrics.test_rows} events learned` : "Loading model"}
          </div>
        </div>
      </header>

      <section className="command-grid">
        <section className="panel command-map-panel">
          <div className="map-header">
            <div className="section-heading">
              <MapPin size={19} />
              <h2>Live operational map</h2>
            </div>
            <div className="map-legend">
              <span><i className="green" /> Low</span>
              <span><i className="yellow" /> Medium</span>
              <span><i className="orange" /> High</span>
              <span><i className="red" /> Critical</span>
            </div>
          </div>
          <RiskMap form={form} result={result} hotspots={hotspots} />
        </section>

        <aside className="panel command-summary">
          <div className="section-heading">
            <Siren size={19} />
            <h2>Operational decision</h2>
          </div>
          {result ? (
            <>
              <div className="score-row vertical">
                <div className="score-ring" style={scoreStyle}>
                  <div>
                    <strong>{result.impact_score}</strong>
                    <span>{result.risk_level}</span>
                  </div>
                </div>
                <div className="score-copy centered">
                  <h3>{result.risk_level} impact</h3>
                  <p>{titleCase(form.event_cause)} at {titleCase(form.junction || form.corridor)}</p>
                </div>
              </div>
              <div className="decision-grid">
                <MetricCard icon={Users} label="Manpower" value={result.recommended_manpower} detail={titleCase(result.response_team_type)} tone="strong" />
                <MetricCard icon={Route} label="Diversion" value={result.diversion_required ? "Activate" : "Standby"} detail={form.corridor} tone={result.diversion_required ? "danger" : "default"} />
                <MetricCard icon={CheckCircle2} label="Barricading" value={result.barricading_required ? "Required" : "No"} detail={result.barricading_required ? "Temporary lane control" : "Monitor only"} />
              </div>
            </>
          ) : (
            <div className="empty-state compact-empty">Select a scenario and run prediction.</div>
          )}
        </aside>
      </section>

      <section className="workspace-grid">
        <form className="panel input-panel" onSubmit={predict}>
          <div className="section-heading">
            <MapPin size={19} />
            <h2>Event intake</h2>
          </div>
          <div className="demo-row">
            {demoScenarios.map((scenario) => (
              <button type="button" key={scenario.name} onClick={() => setForm(scenario)}>
                {scenario.name}
              </button>
            ))}
          </div>
          <div className="form-grid">
            <Field label="Event type" value={form.event_type} options={["planned", "unplanned"]} onChange={(value) => update("event_type", value)} />
            <Field
              label="Event cause"
              value={form.event_cause}
              options={["vip_movement", "procession", "public_event", "tree_fall", "water_logging", "vehicle_breakdown", "construction", "accident", "congestion", "others"]}
              onChange={(value) => update("event_cause", value)}
            />
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
          <button className="primary-button" type="submit" disabled={loading}>
            {loading ? "Running impact model..." : "Predict impact"}
          </button>
          {error && <p className="error">{error}</p>}
        </form>

        <section className="panel result-panel">
          <div className="section-heading">
            <AlertTriangle size={19} />
            <h2>Risk signals</h2>
          </div>
          {result ? (
            <>
              <div className="metric-grid">
                <MetricCard icon={AlertTriangle} label="Closure probability" value={formatPercent(result.road_closure_probability)} detail="Primary model target" />
                <MetricCard icon={BarChart3} label="High priority probability" value={formatPercent(result.high_priority_probability)} detail="Secondary severity signal" />
                <MetricCard icon={RadioTower} label="Hotspot score" value={formatPercent(result.historical_hotspot_score)} detail="Cause, corridor, station, geobin" />
                <MetricCard icon={Clock3} label="Expected duration" value={`${result.expected_duration_hours}h`} detail="Cleaned operational timestamp estimate" />
              </div>
              <section className="recommendation">
                <h3>Recommendation rationale</h3>
                <ul>
                  {result.explanation.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </section>
            </>
          ) : (
            <div className="empty-state">Prediction output appears here after the impact model runs.</div>
          )}
        </section>

        <ScoreBreakdown result={result} />
        <ActionTimeline result={result} />
        <SimilarEvidence result={result} />
        <IncidentReport result={result} form={form} />

        <section className="panel">
          <div className="section-heading">
            <Route size={19} />
            <h2>Similar past events</h2>
          </div>
          {result?.similar_past_events?.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Cause</th>
                    <th>Corridor</th>
                    <th>Priority</th>
                    <th>Closure</th>
                    <th>Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {result.similar_past_events.map((event) => (
                    <tr key={event.id}>
                      <td>{titleCase(event.event_cause)}</td>
                      <td>{event.corridor}</td>
                      <td>{titleCase(event.priority)}</td>
                      <td>{event.requires_road_closure ? "Yes" : "No"}</td>
                      <td>{event.duration_hours ?? "NA"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state">Similar events appear after a prediction.</div>
          )}
        </section>

        <section className="panel">
          <div className="section-heading">
            <AlertTriangle size={19} />
            <h2>Historical hotspots</h2>
          </div>
          <div className="table-wrap compact">
            <table>
              <thead>
                <tr>
                  <th>Cause</th>
                  <th>Police station</th>
                  <th>Events</th>
                  <th>Closure rate</th>
                </tr>
              </thead>
              <tbody>
                {hotspots.slice(0, 8).map((spot, index) => (
                  <tr key={`${spot.event_cause}-${spot.police_station}-${index}`}>
                    <td>{titleCase(spot.event_cause)}</td>
                    <td>{titleCase(spot.police_station)}</td>
                    <td>{spot.event_count}</td>
                    <td>{spot.closure_rate}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel metrics-panel">
          <div className="section-heading">
            <BarChart3 size={19} />
            <h2>Model metrics</h2>
          </div>
          {metrics ? (
            <div className="metrics-list">
              <span>Train rows: {metrics.train_rows}</span>
              <span>Test rows: {metrics.test_rows}</span>
              <span>ROC-AUC: {metrics.road_closure_model?.roc_auc?.toFixed(3)}</span>
              <span>PR-AUC: {metrics.road_closure_model?.average_precision?.toFixed(3)}</span>
              <span>Top 10% capture: {metrics.road_closure_model?.top_10_percent_risk_capture_rate?.toFixed(3)}</span>
              <span>Duration MAE: {metrics.duration_model?.mae_hours?.toFixed(2)}h</span>
            </div>
          ) : (
            <div className="empty-state">Metrics load when the API is running.</div>
          )}
        </section>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
