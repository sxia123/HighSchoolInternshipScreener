import React from "react";

const TABS = [
  { id: "eligible_or_possible", label: "All Matches" },
  { id: "eligible", label: "Verified HS" },
  { id: "possible", label: "Possible" },
  { id: "saved", label: "Watchlist" },
  { id: "rejected", label: "Screened Out" },
];

export default function FilterBar({ filters, onChange, counts, savedCount }) {
  const handleField = (field, value) => {
    onChange({ ...filters, [field]: value });
  };

  const getTabCount = (id) => {
    if (id === "eligible_or_possible") {
      return (counts.eligible || 0) + (counts.possible || 0);
    }
    if (id === "saved") return savedCount;
    return counts[id] ?? 0;
  };

  return (
    <section className="rh-filter-section">
      <div className="rh-tabs-row" role="tablist" aria-label="Eligibility tabs">
        {TABS.map((tab) => {
          const active = filters.status === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={active}
              className={`rh-tab ${active ? "active" : ""}`}
              onClick={() => handleField("status", tab.id)}
            >
              <span>{tab.label}</span>
              <span className="rh-tab-count">{getTabCount(tab.id)}</span>
            </button>
          );
        })}
      </div>

      <div className="rh-subfilters">
        <select
          aria-label="Compensation filter"
          value={filters.compensation}
          onChange={(e) => handleField("compensation", e.target.value)}
        >
          <option value="all">Compensation: All</option>
          <option value="paid_or_stipend">Paid or Stipend</option>
          <option value="paid">Paid Hourly/Salary</option>
          <option value="stipend">Stipend</option>
          <option value="unpaid">Unpaid / Credit</option>
        </select>

        <select
          aria-label="Work mode filter"
          value={filters.work_mode}
          onChange={(e) => handleField("work_mode", e.target.value)}
        >
          <option value="all">Work Mode: All</option>
          <option value="in-person">In-Person</option>
          <option value="hybrid">Hybrid</option>
          <option value="remote">Remote</option>
        </select>

        <select
          aria-label="Source filter"
          value={filters.source_type}
          onChange={(e) => handleField("source_type", e.target.value)}
        >
          <option value="all">Source: All</option>
          <option value="nichable">Nichable HS Directory</option>
          <option value="studentresearchnyc">NY STEM Consortium</option>
          <option value="standoutsearch">StandOutSearch</option>
          <option value="pathwaystoscience">Pathways to Science</option>
          <option value="github_markdown">GitHub HS Lists</option>
          <option value="linkedin_email">LinkedIn Email Alert</option>
          <option value="rss">RSS / Google Alerts</option>
          <option value="greenhouse">Greenhouse ATS</option>
          <option value="lever">Lever ATS</option>
          <option value="ashby">Ashby ATS</option>
          <option value="smartrecruiters">SmartRecruiters ATS</option>
          <option value="remotive">Remotive</option>
        </select>
      </div>
    </section>
  );
}
