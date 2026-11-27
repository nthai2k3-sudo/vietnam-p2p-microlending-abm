import { useEffect, useMemo, useState } from "react";
import { BrowserProvider } from "ethers";

type Agent = {
  id: string; type: string; state: string; balance: number; income: number;
  living_cost: number; loan_amount: number; collateral: number;
  guarantor_stake: number; credit_score: number | null; is_defaulted: boolean;
};
type Snapshot = {
  month: number; version: string; running: boolean; macro_shock: boolean;
  metrics: Record<string, number>; agents: Agent[];
};
const API = "http://127.0.0.1:8000";
const empty: Snapshot = { month: 0, version: "V3", running: false, macro_shock: false, metrics: {}, agents: [] };

function metric(snapshot: Snapshot, key: string, suffix = "") {
  const value = snapshot.metrics[key] ?? 0;
  return `${(value * (suffix === "%" ? 100 : 1)).toFixed(2)}${suffix}`;
}

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot>(empty);
  const [selected, setSelected] = useState<Agent | null>(null);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [wallet, setWallet] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API}/api/simulation/status`).then((r) => r.json()).then(setSnapshot).catch(() => setError("Không kết nối được FastAPI"));
    const socket = new WebSocket("ws://127.0.0.1:8000/ws/simulation");
    socket.onmessage = (event) => { setSnapshot(JSON.parse(event.data)); setError(""); };
    socket.onerror = () => setError("WebSocket chưa sẵn sàng");
    return () => socket.close();
  }, []);

  async function command(path: string, body?: object) {
    setError("");
    try {
      const response = await fetch(`${API}${path}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) throw new Error(await response.text());
      setSnapshot(await response.json());
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Request thất bại"); }
  }

  async function selectVersion(version: string) {
    await command("/api/simulation/config", { version, seed: 42 });
  }

  async function connectWallet() {
    const ethereum = (window as Window & { ethereum?: unknown }).ethereum;
    if (!ethereum) { setError("Cần cài MetaMask để kết nối ví"); return; }
    const provider = new BrowserProvider(ethereum as never);
    const accounts = await provider.send("eth_requestAccounts", []);
    setWallet(accounts[0] ?? "");
  }

  const visibleAgents = useMemo(() => snapshot.agents.filter((agent) =>
    (filter === "all" || agent.type === filter) && agent.id.toLowerCase().includes(search.toLowerCase()),
  ), [snapshot.agents, filter, search]);

  return <main>
    <header>
      <div><p className="eyebrow">VIETNAM P2P MICRO-LENDING</p><h1>Protocol Observatory</h1></div>
      <div className="header-actions"><span className="status">● API {error ? "offline" : "online"}</span><button onClick={connectWallet}>{wallet ? `${wallet.slice(0, 6)}...${wallet.slice(-4)}` : "Connect MetaMask"}</button></div>
    </header>
    {error && <div className="error">{error}</div>}
    <section className="toolbar">
      {["V1", "V2", "V3"].map((version) => <button className={snapshot.version === version ? "active" : ""} onClick={() => selectVersion(version)} key={version}>{version}</button>)}
      <span className="divider" />
      <button onClick={() => command("/api/simulation/start")}>Start</button>
      <button onClick={() => command("/api/simulation/pause")}>Pause</button>
      <button onClick={() => command("/api/simulation/step", { steps: 1 })}>Step</button>
      <button onClick={() => command("/api/simulation/reset", { version: snapshot.version, seed: 42 })}>Reset</button>
      <span className="month">Month {snapshot.month} / 60 {snapshot.macro_shock && " · MACRO SHOCK"}</span>
    </section>
    <section className="metrics">{[
      ["TVL", metric(snapshot, "tvl")], ["Liquidity", metric(snapshot, "available_liquidity")],
      ["Debt", metric(snapshot, "outstanding_debt")], ["NPL", metric(snapshot, "npl", "%")],
      ["Borrow APR", metric(snapshot, "borrow_apr", "%")], ["Supply APR", metric(snapshot, "supply_apr", "%")],
    ].map(([label, value]) => <article className="metric" key={label}><span>{label}</span><strong>{value}</strong></article>)}</section>
    <section className="content">
      <article className="panel network-panel"><div className="panel-title"><h2>Live agent network</h2><span>{visibleAgents.length} agents</span></div>
        <div className="network">{visibleAgents.map((agent, index) => <button title={`${agent.id} · ${agent.state}`} className={`node ${agent.type} ${agent.state.toLowerCase()}`} style={{ left: `${8 + ((index * 37) % 84)}%`, top: `${8 + ((index * 61) % 78)}%` }} onClick={() => setSelected(agent)} key={agent.id}>{agent.id.replace("Agent_", "")}</button>)}</div>
      </article>
      <aside className="panel"><div className="panel-title"><h2>Agent explorer</h2><span>Real Mesa state</span></div>
        <input placeholder="Search agent ID" value={search} onChange={(event) => setSearch(event.target.value)} />
        <select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All types</option><option value="lender">Lenders</option><option value="honest_borrower">Honest borrowers</option><option value="strategic_defaulter">Strategic defaulters</option></select>
        {selected ? <div className="detail"><h3>{selected.id}</h3><p>{selected.type} · {selected.state}</p>{Object.entries(selected).filter(([key]) => !["id", "type", "state"].includes(key)).map(([key, value]) => <div className="row" key={key}><span>{key}</span><b>{String(value)}</b></div>)}</div> : <p className="hint">Click a node to inspect its current state.</p>}
      </aside>
    </section>
  </main>;
}
