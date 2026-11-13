import React, { useCallback, useEffect, useState } from "react";
import { fetchHealth, fetchInternships, triggerScan } from "./api.js";
import FilterBar from "./components/FilterBar.jsx";
import InternshipCard from "./components/InternshipCard.jsx";
import SourcesModal from "./components/SourcesModal.jsx";

const SAVED_STORAGE_KEY = "hs_screener_saved_ids";
const RADIUS_OPTIONS = [
  { value: 10, label: "10M" },
  { value: 25, label: "25M" },
  { value: 50, label: "50M" },
  { value: 100, label: "100M" },
  { value: 0, label: "ALL" },
];

function loadSavedIds() {
  try {
    const raw = localStorage.getItem(SAVED_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export default function App() {
  const [filters, setFilters] = useState({
    status: "eligible_or_possible",
    area: "",
    radius_miles: 50,
    include_remote: true,
    q: "",
    compensation: "all",
    work_mode: "all",
    source_type: "all",
  });

  const [appliedArea, setAppliedArea] = useState("");
  const [health, setHealth] = useState(null);
  const [items, setItems] = useState([]);
  const [allKnownItems, setAllKnownItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [areaResolved, setAreaResolved] = useState(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [banner, setBanner] = useState(null);
  const [modalState, setModalState] = useState({ open: false, tab: "sources" });
  const [savedIds, setSavedIds] = useState(loadSavedIds);

  const toggleSave = (id) => {
    setSavedIds((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      localStorage.setItem(SAVED_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  };

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const apiStatus = filters.status === "saved" ? "all" : filters.status;
      const [healthData, jobsData, watchlistPool] = await Promise.all([
        fetchHealth(),
        fetchInternships({
          ...filters,
          status: apiStatus,
          area: appliedArea,
          limit: 100,
        }),
        savedIds.length > 0
          ? fetchInternships({ status: "all", limit: 200 })
          : Promise.resolve({ items: [] }),
      ]);

      setHealth(healthData);
      setAreaResolved(jobsData.area_resolved);
      setAllKnownItems(watchlistPool.items || []);

      if (filters.status === "saved") {
        const onlySaved = jobsData.items.filter((item) => savedIds.includes(item.id));
        setItems(onlySaved);
        setTotal(onlySaved.length);
      } else {
        setItems(jobsData.items);
        setTotal(jobsData.total);
      }
    } catch (err) {
      setBanner({ type: "error", text: err.message });
    } finally {
      setLoading(false);
    }
  }, [filters, appliedArea, savedIds]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Auto-apply complete 5-digit US ZIP codes or clearing the field without waiting for a button click.
  const handleAreaInputChange = (val) => {
    setFilters((prev) => ({ ...prev, area: val }));
    const trimmed = val.trim();
    if (trimmed === "" || /^\d{5}$/.test(trimmed)) {
      setAppliedArea(trimmed);
    }
  };

  const handleApplyArea = (e) => {
    if (e) e.preventDefault();
    setAppliedArea(filters.area.trim());
  };

  const handleScanNow = async () => {
    setScanning(true);
    setBanner(null);
    try {
      const res = await triggerScan();
      setBanner({
        type: "success",
        text:
          `Scan complete (${res.sources_scanned} sources): ` +
          `${res.eligible} verified HS, ${res.possible} possible, ${res.rejected} screened out.`,
      });
      await loadData();
    } catch (err) {
      setBanner({ type: "error", text: `Scan failed: ${err.message}` });
    } finally {
      setScanning(false);
    }
  };

  const counts = health?.counts || { eligible: 0, possible: 0, rejected: 0, total: 0 };
  const candidateTotal = (counts.eligible || 0) + (counts.possible || 0);
  const grandTotal = Math.max(counts.total || 0, 1);
  const eligiblePct = Math.round(((counts.eligible || 0) / grandTotal) * 100);
  const possiblePct = Math.round(((counts.possible || 0) / grandTotal) * 100);

  const lastScan = health?.last_scan?.finished_at
    ? new Date(health.last_scan.finished_at).toLocaleString()
    : "Never";

  const savedJobs = allKnownItems.filter((j) => savedIds.includes(j.id));

  return (
    <div className="rh-app">
      <header className="rh-navbar">
        <div className="rh-navbar-inner">
          <div className="rh-brand">
            <svg className="rh-logo" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M19.5 3.5C12.5 3.5 7.5 8 6 14.5L3.5 20.5L9.5 18C15.5 16.5 19.5 11.5 19.5 3.5Z"
                fill="#00C805"
              />
              <path
                d="M7 17L15 9"
                stroke="#000000"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
            <span className="rh-wordmark">InternHood</span>
            <span className="rh-badge-lite">HS Screener</span>
          </div>

          <div className="rh-nav-search">
            <input
              type="text"
              aria-label="Search internships"
              placeholder="Search roles, companies, skills (e.g. robotics, paid)..."
              value={filters.q}
              onChange={(e) => setFilters((prev) => ({ ...prev, q: e.target.value }))}
            />
          </div>

          <div className="rh-nav-actions">
            <button
              type="button"
              className="rh-btn rh-btn-ghost"
              onClick={() => setModalState({ open: true, tab: "sources" })}
            >
              Sources &amp; LinkedIn
            </button>
            <button
              type="button"
              className="rh-btn rh-btn-primary"
              onClick={handleScanNow}
              disabled={scanning}
            >
              {scanning ? "Scanning..." : "Scan Now"}
            </button>
          </div>
        </div>
      </header>

      <div className="rh-layout">
        <main className="rh-main-col">
          {banner && (
            <div className={`rh-alert ${banner.type === "error" ? "error" : "success"}`}>
              {banner.text}
            </div>
          )}

          <section className="rh-hero">
            <div className="rh-hero-eyebrow">
              <span>HIGH SCHOOL INTERNSHIP RADAR</span>
              {areaResolved ? (
                <span className="rh-area-chip">
                  {areaResolved.display_name} ·{" "}
                  {filters.radius_miles > 0 ? `${filters.radius_miles} mi` : "Anywhere"}
                </span>
              ) : appliedArea ? (
                <span className="rh-area-chip">Area: {appliedArea}</span>
              ) : (
                <span className="rh-area-chip muted">All Locations</span>
              )}
            </div>

            <div className="rh-hero-number">{total}</div>

            <div className="rh-hero-deltas">
              <span className="rh-delta-up">▲ {counts.eligible || 0} Verified HS</span>
              <span className="rh-delta-mid">● {counts.possible || 0} Possible</span>
              <span className="rh-delta-down">▼ {counts.rejected || 0} Screened Out</span>
              <span className="rh-delta-muted">· {candidateTotal} total candidates</span>
            </div>

            <div className="rh-spark-bar" aria-label="Screening distribution">
              <div className="rh-spark-green" style={{ width: `${eligiblePct}%` }} />
              <div className="rh-spark-amber" style={{ width: `${possiblePct}%` }} />
            </div>
          </section>

          <FilterBar
            filters={filters}
            onChange={setFilters}
            counts={counts}
            savedCount={savedIds.length}
          />

          {loading ? (
            <div className="rh-empty">Loading opportunities...</div>
          ) : items.length === 0 ? (
            <div className="rh-empty">
              <h3>No matching internships in this view</h3>
              <p>
                {appliedArea
                  ? `No candidate listings matched within ${filters.radius_miles || "any"} miles of ${areaResolved?.display_name || appliedArea}. Try expanding the radius to 100M/ALL or adding a local LinkedIn Google Alert RSS feed.`
                  : "Click Scan Now or open Sources & LinkedIn to import alerts."}
              </p>
            </div>
          ) : (
            <div className="rh-feed">
              {items.map((item) => (
                <InternshipCard
                  key={item.id}
                  item={item}
                  isSaved={savedIds.includes(item.id)}
                  onToggleSave={toggleSave}
                />
              ))}
            </div>
          )}
        </main>

        <aside className="rh-sidebar">
          <form className="rh-ticket-card" onSubmit={handleApplyArea}>
            <div className="rh-ticket-header">
              <span>Area Radar</span>
              <span className="rh-db-pill">{health?.database_backend || "sqlite"}</span>
            </div>

            <div className="rh-field">
              <label htmlFor="sidebar-area-input">US ZIP Code or City, ST</label>
              <input
                id="sidebar-area-input"
                type="text"
                placeholder="e.g. 28001 or Austin, TX"
                value={filters.area}
                onChange={(e) => handleAreaInputChange(e.target.value)}
              />
            </div>

            <div className="rh-radius-pills" role="group" aria-label="Distance radius">
              {RADIUS_OPTIONS.map((opt) => {
                const active = filters.radius_miles === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    className={`rh-radius-pill ${active ? "active" : ""}`}
                    onClick={() => {
                      setFilters((prev) => ({ ...prev, radius_miles: opt.value }));
                      if (filters.area.trim() !== appliedArea) {
                        setAppliedArea(filters.area.trim());
                      }
                    }}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>

            <label className="rh-switch-row">
              <span>Include Remote &amp; Nationwide</span>
              <input
                type="checkbox"
                checked={filters.include_remote}
                onChange={(e) =>
                  setFilters((prev) => ({ ...prev, include_remote: e.target.checked }))
                }
              />
            </label>

            <button type="submit" className="rh-btn rh-btn-primary rh-btn-full">
              Update Area Radar
            </button>

            {appliedArea && (
              <button
                type="button"
                className="rh-clear-link"
                onClick={() => {
                  setFilters((prev) => ({ ...prev, area: "" }));
                  setAppliedArea("");
                }}
              >
                Clear area filter
              </button>
            )}

            <div className="rh-ticket-meta">
              {areaResolved ? (
                <div>
                  <strong>Resolved:</strong> {areaResolved.display_name}
                </div>
              ) : appliedArea ? (
                <div>
                  <strong>Matching text:</strong> “{appliedArea}”
                </div>
              ) : (
                <div>Showing all scanned US &amp; remote listings.</div>
              )}
              <div className="rh-muted-sm">Last scan: {lastScan}</div>
            </div>
          </form>

          <section className="rh-ticket-card">
            <div className="rh-ticket-header">
              <span>Watchlist</span>
              <span className="rh-muted-sm">{savedIds.length} saved</span>
            </div>

            {savedJobs.length === 0 ? (
              <p className="rh-muted-sm">
                Star any internship (☆) to pin it to your watchlist for quick applying.
              </p>
            ) : (
              <div className="rh-watchlist">
                {savedJobs.map((job) => (
                  <div key={job.id} className="rh-watch-item">
                    <a
                      href={job.apply_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rh-watch-link"
                    >
                      <strong>{job.company}</strong>
                      <span>{job.title}</span>
                    </a>
                    <button
                      type="button"
                      className="rh-watch-remove"
                      onClick={() => toggleSave(job.id)}
                      aria-label={`Remove ${job.title} from watchlist`}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="rh-ticket-card rh-quick-links">
            <div className="rh-ticket-header">
              <span>LinkedIn Tools (Keyless)</span>
            </div>
            <button
              type="button"
              className="rh-quick-action"
              onClick={() => setModalState({ open: true, tab: "linkedin" })}
            >
              <span>Generate LinkedIn Google Alert RSS</span>
              <span className="rh-green-arrow">→</span>
            </button>
            <button
              type="button"
              className="rh-quick-action"
              onClick={() => setModalState({ open: true, tab: "email" })}
            >
              <span>Import LinkedIn Job Alert Email</span>
              <span className="rh-green-arrow">→</span>
            </button>
          </section>
        </aside>
      </div>

      <SourcesModal
        isOpen={modalState.open}
        initialTab={modalState.tab}
        onClose={() => setModalState((prev) => ({ ...prev, open: false }))}
        currentArea={filters.area}
        onDataChanged={loadData}
      />
    </div>
  );
}
