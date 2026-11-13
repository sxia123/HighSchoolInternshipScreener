import React, { useEffect, useState } from "react";
import {
  createSource,
  deleteSource,
  fetchLinkedinHelper,
  fetchSources,
  ingestEmailFile,
  ingestEmailText,
  updateSource,
} from "../api.js";

export default function SourcesModal({
  isOpen,
  initialTab = "sources",
  onClose,
  currentArea,
  onDataChanged,
}) {
  const [activeTab, setActiveTab] = useState(initialTab);
  const [sources, setSources] = useState([]);
  const [loadingSources, setLoadingSources] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("greenhouse");
  const [newTarget, setNewTarget] = useState("");
  const [newAreaHint, setNewAreaHint] = useState(currentArea || "");

  const [helperArea, setHelperArea] = useState(currentArea || "");
  const [helperData, setHelperData] = useState(null);

  const [rawEmail, setRawEmail] = useState("");
  const [emailArea, setEmailArea] = useState(currentArea || "");
  const [emailFile, setEmailFile] = useState(null);
  const [importing, setImporting] = useState(false);

  const loadSources = async () => {
    setLoadingSources(true);
    setError("");
    try {
      const list = await fetchSources();
      setSources(list);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingSources(false);
    }
  };

  useEffect(() => {
    if (!isOpen) return;
    setActiveTab(initialTab || "sources");
    setError("");
    setNotice("");
    loadSources();
    setHelperArea(currentArea || "");
    setEmailArea(currentArea || "");
    setNewAreaHint(currentArea || "");
  }, [isOpen, initialTab, currentArea]);

  useEffect(() => {
    if (!isOpen || activeTab !== "linkedin") return;
    fetchLinkedinHelper(helperArea)
      .then(setHelperData)
      .catch((err) => setError(err.message));
  }, [isOpen, activeTab, helperArea]);

  if (!isOpen) return null;

  const handleAddSource = async (e) => {
    e.preventDefault();
    setError("");
    setNotice("");
    try {
      await createSource({
        name: newName,
        source_type: newType,
        target: newTarget,
        area_hint: newAreaHint,
        enabled: true,
      });
      setNewName("");
      setNewTarget("");
      setNotice("Source added. Click 'Scan Now' to pull its postings.");
      await loadSources();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleToggle = async (src) => {
    try {
      await updateSource(src.id, { enabled: !src.enabled });
      await loadSources();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteSource(id);
      await loadSources();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleImportEmail = async (e) => {
    e.preventDefault();
    setError("");
    setNotice("");
    setImporting(true);
    try {
      const res = emailFile
        ? await ingestEmailFile(emailFile, emailArea)
        : await ingestEmailText(rawEmail, emailArea);
      setNotice(
        `Parsed ${res.parsed_count} LinkedIn links: ${res.eligible} verified high school, ` +
          `${res.possible} possible, ${res.rejected} screened out.`
      );
      setRawEmail("");
      setEmailFile(null);
      onDataChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="rh-modal-backdrop" onClick={onClose}>
      <div className="rh-modal" onClick={(e) => e.stopPropagation()}>
        <div className="rh-modal-header">
          <h2>Sources &amp; LinkedIn Alerts</h2>
          <button type="button" className="rh-icon-close" onClick={onClose} aria-label="Close modal">
            ✕
          </button>
        </div>

        <div className="rh-tabs-row">
          <button
            type="button"
            className={`rh-tab ${activeTab === "sources" ? "active" : ""}`}
            onClick={() => setActiveTab("sources")}
          >
            Job Feeds ({sources.length})
          </button>
          <button
            type="button"
            className={`rh-tab ${activeTab === "linkedin" ? "active" : ""}`}
            onClick={() => setActiveTab("linkedin")}
          >
            LinkedIn Google Alert RSS
          </button>
          <button
            type="button"
            className={`rh-tab ${activeTab === "email" ? "active" : ""}`}
            onClick={() => setActiveTab("email")}
          >
            Import Alert Email
          </button>
        </div>

        {error && <div className="rh-alert error">{error}</div>}
        {notice && <div className="rh-alert success">{notice}</div>}

        {activeTab === "sources" && (
          <div className="rh-modal-body">
            <form className="rh-subcard" onSubmit={handleAddSource}>
              <h4>Add Company Board or RSS Feed</h4>
              <div className="rh-form-grid">
                <input
                  type="text"
                  required
                  placeholder="Display Name (e.g. Local Youth RSS)"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
                <select value={newType} onChange={(e) => setNewType(e.target.value)}>
                  <option value="greenhouse">Greenhouse (slug)</option>
                  <option value="lever">Lever (slug)</option>
                  <option value="ashby">Ashby (slug)</option>
                  <option value="smartrecruiters">SmartRecruiters (slug)</option>
                  <option value="rss">RSS / Google Alert Feed (URL)</option>
                  <option value="nichable">Nichable Local / HS Directory (URL)</option>
                  <option value="studentresearchnyc">NY STEM Research Consortium (URL)</option>
                  <option value="github_markdown">GitHub HS Markdown List (raw URL)</option>
                  <option value="standoutsearch">StandOutSearch Directory (URL)</option>
                  <option value="pathwaystoscience">Pathways to Science (URL)</option>
                  <option value="remotive">Remotive (search term)</option>
                </select>
                <input
                  type="text"
                  required
                  placeholder={
                    [
                      "rss",
                      "nichable",
                      "studentresearchnyc",
                      "github_markdown",
                      "standoutsearch",
                      "pathwaystoscience",
                    ].includes(newType)
                      ? "https://..."
                      : "Company board slug (e.g. stripe)"
                  }
                  value={newTarget}
                  onChange={(e) => setNewTarget(e.target.value)}
                />
                <input
                  type="text"
                  placeholder="Area hint (e.g. Raleigh, NC)"
                  value={newAreaHint}
                  onChange={(e) => setNewAreaHint(e.target.value)}
                />
              </div>
              <button type="submit" className="rh-btn rh-btn-primary rh-btn-sm">
                + Add Source
              </button>
            </form>

            <div className="rh-source-list">
              {loadingSources ? (
                <p className="rh-muted">Loading sources...</p>
              ) : (
                sources.map((src) => (
                  <div key={src.id} className="rh-source-row">
                    <div>
                      <div className="rh-source-name">
                        <strong>{src.name}</strong>
                        <span className="rh-mini-tag">{src.source_type}</span>
                      </div>
                      <div className="rh-source-target">{src.target}</div>
                      {src.last_error && (
                        <div className="rh-source-err">Error: {src.last_error}</div>
                      )}
                    </div>
                    <div className="rh-source-btns">
                      <button
                        type="button"
                        className="rh-btn rh-btn-ghost rh-btn-sm"
                        onClick={() => handleToggle(src)}
                      >
                        {src.enabled ? "Active" : "Paused"}
                      </button>
                      <button
                        type="button"
                        className="rh-btn rh-btn-danger rh-btn-sm"
                        onClick={() => handleDelete(src.id)}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {activeTab === "linkedin" && (
          <div className="rh-modal-body">
            <p className="rh-muted">
              LinkedIn restricts scraping and enterprise APIs. Use a free{" "}
              <strong>Google Alerts RSS feed</strong> targeting LinkedIn job postings in your
              US city or ZIP — GitHub Actions scans it automatically with zero API keys.
            </p>
            <div className="rh-field">
              <label htmlFor="helper-area">Target City / State</label>
              <input
                id="helper-area"
                type="text"
                placeholder="e.g. Raleigh, NC"
                value={helperArea}
                onChange={(e) => setHelperArea(e.target.value)}
              />
            </div>

            {helperData && (
              <>
                <ol className="rh-steps">
                  {helperData.instructions.map((step, i) => (
                    <li key={i}>{step}</li>
                  ))}
                </ol>
                {helperData.queries.map((qItem, idx) => (
                  <div key={idx} className="rh-subcard">
                    <div className="rh-query-top">
                      <strong>{qItem.label}</strong>
                      <div className="rh-source-btns">
                        <button
                          type="button"
                          className="rh-btn rh-btn-ghost rh-btn-sm"
                          onClick={() => navigator.clipboard?.writeText(qItem.query)}
                        >
                          Copy Query
                        </button>
                        <a
                          className="rh-btn rh-btn-primary rh-btn-sm"
                          href={qItem.google_alerts_url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          Open Google Alerts ↗
                        </a>
                      </div>
                    </div>
                    <code className="rh-code">{qItem.query}</code>
                  </div>
                ))}
              </>
            )}
          </div>
        )}

        {activeTab === "email" && (
          <div className="rh-modal-body">
            <p className="rh-muted">
              Create free LinkedIn Job Alerts in your account, then upload a saved{" "}
              <code>.eml</code> file or paste the email body below to screen every link.
            </p>
            <form onSubmit={handleImportEmail} className="rh-email-form">
              <div className="rh-field">
                <label htmlFor="email-area">Default US City / ZIP (if missing from email)</label>
                <input
                  id="email-area"
                  type="text"
                  placeholder="e.g. 27514 or Raleigh, NC"
                  value={emailArea}
                  onChange={(e) => setEmailArea(e.target.value)}
                />
              </div>

              <div className="rh-field">
                <label htmlFor="eml-upload">Upload .eml file (optional)</label>
                <input
                  id="eml-upload"
                  type="file"
                  accept=".eml,.txt,.html"
                  onChange={(e) => setEmailFile(e.target.files?.[0] || null)}
                />
              </div>

              <div className="rh-field">
                <label htmlFor="raw-email-box">Or paste LinkedIn alert email HTML/text</label>
                <textarea
                  id="raw-email-box"
                  rows={6}
                  placeholder="Paste email text or HTML containing linkedin.com/jobs/view/... links"
                  value={rawEmail}
                  onChange={(e) => setRawEmail(e.target.value)}
                  disabled={Boolean(emailFile)}
                />
              </div>

              <button
                type="submit"
                className="rh-btn rh-btn-primary"
                disabled={importing || (!emailFile && rawEmail.trim().length < 10)}
              >
                {importing ? "Screening..." : "Import & Screen Alert"}
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
