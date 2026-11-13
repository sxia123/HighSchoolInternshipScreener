import React from "react";

const STATUS_META = {
  eligible: { label: "Verified HS", className: "rh-pill-green" },
  possible: { label: "Possible", className: "rh-pill-amber" },
  rejected: { label: "Screened Out", className: "rh-pill-coral" },
};

const COMP_LABEL = {
  paid: "Paid",
  stipend: "Stipend",
  unpaid: "Unpaid",
  unspecified: "Pay Unlisted",
};

function companyMonogram(company) {
  const cleaned = (company || "?").trim();
  return cleaned.slice(0, 2).toUpperCase();
}

export default function InternshipCard({ item, isSaved, onToggleSave }) {
  const statusInfo = STATUS_META[item.eligibility_status] || STATUS_META.possible;
  const dateText = item.posted_at
    ? new Date(item.posted_at).toLocaleDateString()
    : new Date(item.last_seen_at).toLocaleDateString();

  return (
    <article className="rh-row-card">
      <div className="rh-row-main">
        <div className="rh-row-left">
          <div className="rh-monogram" aria-hidden="true">
            {companyMonogram(item.company)}
          </div>
          <div className="rh-row-info">
            <div className="rh-row-title-line">
              <a
                className="rh-row-title"
                href={item.apply_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {item.title}
              </a>
            </div>
            <div className="rh-row-sub">
              <span className="rh-company">{item.company}</span>
              <span className="rh-dot">·</span>
              <span>{item.location || "Location unlisted"}</span>
              {item.work_mode && item.work_mode !== "unspecified" && (
                <>
                  <span className="rh-dot">·</span>
                  <span className="rh-cap">{item.work_mode}</span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="rh-row-right">
          <div className="rh-metrics-col">
            <span className={`rh-pill ${statusInfo.className}`}>
              {statusInfo.label} · {item.eligibility_score}%
            </span>
            {item.distance_miles !== null && item.distance_miles !== undefined ? (
              <span className="rh-distance">{item.distance_miles} mi away</span>
            ) : (
              <span className="rh-comp-tag">
                {COMP_LABEL[item.compensation] || "Pay Unlisted"}
              </span>
            )}
          </div>

          <button
            type="button"
            className={`rh-star-btn ${isSaved ? "saved" : ""}`}
            onClick={() => onToggleSave(item.id)}
            title={isSaved ? "Remove from watchlist" : "Add to watchlist"}
            aria-label={isSaved ? "Remove from watchlist" : "Add to watchlist"}
          >
            {isSaved ? "★" : "☆"}
          </button>
        </div>
      </div>

      {item.eligibility_status === "rejected" && item.rejection_reason ? (
        <div className="rh-evidence rejected">
          <span className="rh-ev-label">Filtered:</span> {item.rejection_reason}
          {item.evidence_quote && (
            <span className="rh-ev-quote"> — “{item.evidence_quote}”</span>
          )}
        </div>
      ) : (
        item.evidence_quote && (
          <div className="rh-evidence">
            <span className="rh-ev-label">Screener note:</span> “{item.evidence_quote}”
          </div>
        )
      )}

      <div className="rh-row-footer">
        <div className="rh-tag-strip">
          {item.grade_or_age && <span className="rh-mini-tag">{item.grade_or_age}</span>}
          <span className="rh-mini-tag">
            {COMP_LABEL[item.compensation] || "Pay Unlisted"}
          </span>
          <span className="rh-source-text">
            {item.source_type === "remotive" && item.source_url ? (
              <a href={item.source_url} target="_blank" rel="noopener noreferrer">
                Remotive
              </a>
            ) : (
              item.source_label
            )}
            {" · "}
            {dateText}
          </span>
        </div>

        <a
          className="rh-apply-link"
          href={item.apply_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Apply ↗
        </a>
      </div>
    </article>
  );
}
