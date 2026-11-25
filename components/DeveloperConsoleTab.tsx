"use client";

import React, { useCallback, useEffect, useState } from "react";
import { fastApiClient, FastAPIApiKey } from "@/lib/fastapi-client";
import {
  Key,
  Plus,
  RefreshCw,
  Trash2,
  Copy,
  Check,
  ShieldAlert,
  Terminal,
  AlertTriangle,
} from "lucide-react";

export function DeveloperConsoleTab() {
  const [keys, setKeys] = useState<FastAPIApiKey[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [envFilter, setEnvFilter] = useState<"all" | "test" | "live">("all");

  // Create key form state
  const [newName, setNewName] = useState("Backend Integration Key");
  const [newEnv, setNewEnv] = useState<"test" | "live">("test");
  const [newQuota, setNewQuota] = useState(10000);
  const [isCreating, setIsCreating] = useState(false);

  // One-time secret reveal
  const [revealedSecret, setRevealedSecret] = useState<{ apiKey: string; name: string; environment: string } | null>(null);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [snippetLang, setSnippetLang] = useState<"curl" | "js" | "python">("curl");

  const isAuthenticated = typeof window !== "undefined" && fastApiClient.isAuthenticated();

  const loadKeys = useCallback(async () => {
    if (!isAuthenticated) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await fastApiClient.listApiKeys();
      setKeys(data);
    } catch (err: any) {
      setError(err.message || "Unable to load API keys.");
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setIsCreating(true);
    setError(null);
    try {
      const created = await fastApiClient.createApiKey({
        name: newName.trim(),
        environment: newEnv,
        monthly_quota: newQuota,
      });
      setRevealedSecret({ apiKey: created.api_key, name: created.name, environment: created.environment });
      setCopiedSecret(false);
      await loadKeys();
    } catch (err: any) {
      setError(err.message || "Failed to create API key.");
    } finally {
      setIsCreating(false);
    }
  };

  const handleRotate = async (keyId: string) => {
    setError(null);
    try {
      const rotated = await fastApiClient.rotateApiKey(keyId);
      setRevealedSecret({ apiKey: rotated.api_key, name: rotated.name, environment: rotated.environment });
      setCopiedSecret(false);
      await loadKeys();
    } catch (err: any) {
      setError(err.message || "Failed to rotate API key.");
    }
  };

  const handleRevoke = async (keyId: string) => {
    if (!confirm("Revoke this API key immediately? Any integration using it will receive HTTP 401.")) return;
    setError(null);
    try {
      await fastApiClient.revokeApiKey(keyId);
      await loadKeys();
    } catch (err: any) {
      setError(err.message || "Failed to revoke API key.");
    }
  };

  const handleCopySecret = () => {
    if (!revealedSecret) return;
    navigator.clipboard.writeText(revealedSecret.apiKey);
    setCopiedSecret(true);
    setTimeout(() => setCopiedSecret(false), 2500);
  };

  const filteredKeys = keys.filter((k) => envFilter === "all" || (k.environment || "live") === envFilter);
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const sampleKey = revealedSecret?.apiKey || "pl_test_your_api_key_here";

  const snippets = {
    curl: `curl -X GET "${apiBase}/api/v1/postcodes/commercial/lookup?code=EK-01-A03-FK-01" \\\n  -H "x-api-key: ${sampleKey}"`,
    js: `const res = await fetch("${apiBase}/api/v1/postcodes/commercial/cleanse", {\n  method: "POST",\n  headers: {\n    "Content-Type": "application/json",\n    "x-api-key": "${sampleKey}"\n  },\n  body: JSON.stringify({\n    address: "14 Admiralty Way, Lekki Phase 1, Lagos",\n    verification_mode: "nipost_validate"\n  })\n});\nconst data = await res.json();`,
    python: `import requests\n\nres = requests.post(\n    "${apiBase}/api/v1/postcodes/commercial/cleanse",\n    headers={"x-api-key": "${sampleKey}"},\n    json={\n        "address": "14 Admiralty Way, Lekki Phase 1, Lagos",\n        "verification_mode": "nipost_validate",\n    },\n)\nprint(res.json())`,
  };

  return (
    <div>
      {!isAuthenticated && (
        <section className="panel" style={{ borderLeft: "4px solid #d97706", background: "#fffbeb" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", fontSize: "13px", color: "#92400e" }}>
            <AlertTriangle size={18} color="#d97706" />
            <span>
              <strong>Authentication Required:</strong> Sign in with your Merchant or Admin FastAPI session to issue, rotate, and monitor <code>pl_test_</code> and <code>pl_live_</code> API keys.
            </span>
          </div>
        </section>
      )}

      {error && (
        <section className="panel" style={{ borderLeft: "4px solid #dc2626", background: "#fef2f2", padding: "12px 16px" }}>
          <div style={{ fontSize: "13px", color: "#991b1b" }}>
            <strong>API Key Console Notice:</strong> {error}
          </div>
        </section>
      )}

      {/* One-time plaintext secret banner */}
      {revealedSecret && (
        <section className="panel" style={{ borderLeft: "4px solid #16a34a", background: "#f0fdf4" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "12px", flexWrap: "wrap" }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: "13px", fontWeight: 700, color: "#166534", marginBottom: "4px" }}>
                One-Time API Key Secret ({revealedSecret.name} · {revealedSecret.environment.toUpperCase()})
              </div>
              <p style={{ margin: "0 0 8px", fontSize: "12px", color: "#14532d" }}>
                Copy and store this credential securely now. For your security, the plaintext key cannot be retrieved again.
              </p>
              <code style={{ display: "block", background: "#ffffff", border: "1px solid #86efac", padding: "10px 12px", borderRadius: "6px", fontSize: "12px", wordBreak: "break-all", color: "#0f172a" }}>
                {revealedSecret.apiKey}
              </code>
            </div>
            <div style={{ display: "flex", gap: "8px" }}>
              <button type="button" className="primary" onClick={handleCopySecret}>
                {copiedSecret ? <Check size={14} /> : <Copy size={14} />}
                {copiedSecret ? "Copied" : "Copy Key"}
              </button>
              <button type="button" className="outline" onClick={() => setRevealedSecret(null)}>
                Dismiss
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Create API Key */}
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Developer API Key Management</h2>
            <p>
              Issue isolated PostcodeLink <code>pl_test_</code> (sandbox/integration) and <code>pl_live_</code> (production) credentials with monthly quota metering.
            </p>
          </div>
          <button type="button" className="outline" onClick={loadKeys} disabled={isLoading || !isAuthenticated}>
            <RefreshCw size={14} className={isLoading ? "spin" : ""} /> Refresh Keys
          </button>
        </div>

        <form onSubmit={handleCreate} className="form-grid" style={{ alignItems: "end" }}>
          <div className="form-group">
            <label>Key Name</label>
            <input
              type="text"
              required
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. Checkout Service"
              disabled={!isAuthenticated}
            />
          </div>

          <div className="form-group">
            <label>Developer Environment</label>
            <select value={newEnv} onChange={(e) => setNewEnv(e.target.value as "test" | "live")} disabled={!isAuthenticated}>
              <option value="test">Test Environment (pl_test_)</option>
              <option value="live">Live Environment (pl_live_)</option>
            </select>
          </div>

          <div className="form-group">
            <label>Monthly Quota (Requests)</label>
            <input
              type="number"
              min={1}
              max={10000000}
              value={newQuota}
              onChange={(e) => setNewQuota(Number(e.target.value))}
              disabled={!isAuthenticated}
            />
          </div>

          <div className="form-group">
            <button type="submit" className="primary" disabled={isCreating || !isAuthenticated}>
              <Plus size={15} /> {isCreating ? "Issuing..." : "Generate API Key"}
            </button>
          </div>
        </form>

        {/* Environment Filter & Keys Table */}
        <div style={{ marginTop: "20px", display: "flex", gap: "8px", marginBottom: "12px" }}>
          {(["all", "test", "live"] as const).map((env) => (
            <button
              key={env}
              type="button"
              className={envFilter === env ? "primary" : "outline"}
              style={{ height: "30px", fontSize: "12px", padding: "0 12px" }}
              onClick={() => setEnvFilter(env)}
            >
              {env === "all" ? "All Keys" : env === "test" ? "Test (pl_test_)" : "Live (pl_live_)"}
            </button>
          ))}
        </div>

        {filteredKeys.length === 0 ? (
          <div style={{ padding: "24px", textAlign: "center", background: "#f8fafc", borderRadius: "8px", fontSize: "13px", color: "#64748b" }}>
            {isAuthenticated ? "No API keys found for this environment." : "Sign in to view and manage your API keys."}
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--line)", textAlign: "left", color: "#64748b" }}>
                  <th style={{ padding: "10px 8px" }}>Name</th>
                  <th style={{ padding: "10px 8px" }}>Environment</th>
                  <th style={{ padding: "10px 8px" }}>Prefix</th>
                  <th style={{ padding: "10px 8px" }}>Monthly Usage / Quota</th>
                  <th style={{ padding: "10px 8px" }}>Rate Limit</th>
                  <th style={{ padding: "10px 8px" }}>Status</th>
                  <th style={{ padding: "10px 8px", textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredKeys.map((k) => {
                  const pct = Math.min(100, Math.round((k.period_usage_count / Math.max(1, k.monthly_quota)) * 100));
                  const isActive = k.is_active && !k.is_revoked;
                  return (
                    <tr key={k.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                      <td style={{ padding: "10px 8px", fontWeight: 600 }}>{k.name}</td>
                      <td style={{ padding: "10px 8px" }}>
                        <span className={`pill ${(k.environment || "live") === "test" ? "amber" : "blue"}`}>
                          {(k.environment || "live").toUpperCase()}
                        </span>
                      </td>
                      <td style={{ padding: "10px 8px" }}>
                        <code>{k.key_prefix}...</code>
                      </td>
                      <td style={{ padding: "10px 8px", minWidth: "160px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", marginBottom: "4px" }}>
                          <span>{k.period_usage_count.toLocaleString()} / {k.monthly_quota.toLocaleString()}</span>
                          <span>{pct}%</span>
                        </div>
                        <div style={{ height: "6px", background: "#e2e8f0", borderRadius: "99px", overflow: "hidden" }}>
                          <div style={{ width: `${pct}%`, height: "100%", background: pct > 90 ? "#dc2626" : "#0284c7" }} />
                        </div>
                      </td>
                      <td style={{ padding: "10px 8px" }}>{k.rate_limit_per_minute} req/min</td>
                      <td style={{ padding: "10px 8px" }}>
                        <span className={`pill ${isActive ? "green" : "gray"}`}>
                          {isActive ? "Active" : "Revoked"}
                        </span>
                      </td>
                      <td style={{ padding: "10px 8px", textAlign: "right" }}>
                        {isActive && (
                          <div style={{ display: "inline-flex", gap: "6px" }}>
                            <button type="button" className="outline" style={{ height: "28px", fontSize: "11px", padding: "0 8px" }} onClick={() => handleRotate(k.id)}>
                              <RefreshCw size={11} /> Rotate
                            </button>
                            <button type="button" className="danger-btn" style={{ height: "28px", fontSize: "11px", padding: "0 8px" }} onClick={() => handleRevoke(k.id)}>
                              <Trash2 size={11} /> Revoke
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Quickstart & Error Reference */}
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Commercial API Quickstart & Rate-Limit Reference</h2>
            <p>Authenticate with the <code>x-api-key</code> header. Responses clearly separate <code>local_reference</code>, <code>sandbox_verified</code>, and <code>official_verified</code> provenance.</p>
          </div>
          <div style={{ display: "flex", gap: "6px" }}>
            {(["curl", "js", "python"] as const).map((lang) => (
              <button
                key={lang}
                type="button"
                className={snippetLang === lang ? "primary" : "outline"}
                style={{ height: "28px", fontSize: "11px", padding: "0 10px" }}
                onClick={() => setSnippetLang(lang)}
              >
                <Terminal size={11} /> {lang.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <pre style={{ background: "#0f172a", color: "#e2e8f0", padding: "14px", borderRadius: "8px", fontSize: "12px", overflowX: "auto", margin: "0 0 14px" }}>
          <code>{snippets[snippetLang]}</code>
        </pre>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "10px", fontSize: "12px" }}>
          <div style={{ background: "#f8fafc", padding: "10px 12px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
            <strong style={{ color: "#dc2626" }}>HTTP 401 Unauthorized</strong>
            <div style={{ color: "#475569", marginTop: "2px" }}>Missing, expired, or revoked <code>x-api-key</code> header.</div>
          </div>
          <div style={{ background: "#f8fafc", padding: "10px 12px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
            <strong style={{ color: "#d97706" }}>HTTP 429 Too Many Requests</strong>
            <div style={{ color: "#475569", marginTop: "2px" }}>Per-minute sliding window or monthly quota exceeded.</div>
          </div>
          <div style={{ background: "#f8fafc", padding: "10px 12px", borderRadius: "6px", border: "1px solid #e2e8f0" }}>
            <strong style={{ color: "#0284c7" }}>HTTP 503 Service Unavailable</strong>
            <div style={{ color: "#475569", marginTop: "2px" }}>Strict NIPOST mode failed closed (sandbox key or upstream outage).</div>
          </div>
        </div>
      </section>
    </div>
  );
}
