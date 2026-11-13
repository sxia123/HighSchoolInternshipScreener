const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const payload = await res.json();
      if (payload?.detail) detail = payload.detail;
    } catch {
      // Ignore JSON parse failure on non-JSON error responses.
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export function fetchHealth() {
  return request("/api/health");
}

export function fetchInternships(params) {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      qs.set(key, String(value));
    }
  });
  return request(`/api/internships?${qs.toString()}`);
}

export function triggerScan(sourceIds = null) {
  return request("/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(sourceIds ? { source_ids: sourceIds } : {}),
  });
}

export function fetchSources() {
  return request("/api/sources");
}

export function createSource(payload) {
  return request("/api/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateSource(id, payload) {
  return request(`/api/sources/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteSource(id) {
  return request(`/api/sources/${id}`, { method: "DELETE" });
}

export function fetchLinkedinHelper(area) {
  const qs = new URLSearchParams({ area: area || "" });
  return request(`/api/linkedin-helper?${qs.toString()}`);
}

export function ingestEmailText(rawEmail, defaultArea = "") {
  return request("/api/ingest/email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_email: rawEmail, default_area: defaultArea }),
  });
}

export function ingestEmailFile(file, defaultArea = "") {
  const form = new FormData();
  form.append("file", file);
  form.append("default_area", defaultArea);
  return request("/api/ingest/email-file", {
    method: "POST",
    body: form,
  });
}
