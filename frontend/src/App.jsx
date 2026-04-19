import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws";

const ROLE_COLOR = { BAT: "#3b82f6", BOWL: "#ef4444", ALL: "#f59e0b", WK: "#8b5cf6" };
const ROLE_LABEL = { BAT: "Batter", BOWL: "Bowler", ALL: "All-rounder", WK: "Keeper" };

function downloadCSV(filename, rows) {
  const csvContent = rows.map(e => e.join(",")).join("\n");
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.setAttribute("href", url);
  link.setAttribute("download", filename);
  link.style.visibility = 'hidden';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function useWebSocket(onMessage) {
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let isIntentionalClose = false;
    const connect = () => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => { setConnected(false); if (!isIntentionalClose) setTimeout(connect, 2000); };
      ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    };
    connect();
    return () => { isIntentionalClose = true; wsRef.current?.close(); };
  }, [onMessage]);

  return connected;
}

function Badge({ role }) {
  return (
    <span style={{
      background: ROLE_COLOR[role] + "22", color: ROLE_COLOR[role],
      fontSize: 11, fontWeight: 600, padding: "2px 8px",
      borderRadius: 20, letterSpacing: "0.04em",
      border: `1px solid ${ROLE_COLOR[role]}44`
    }}>{role}</span>
  );
}

function BudgetBar({ remaining, total }) {
  const pct = Math.round((remaining / total) * 100);
  const color = pct > 50 ? "#22c55e" : pct > 25 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ width: "100%", marginTop: 4 }}>
      <div style={{ height: 4, background: "#ffffff18", borderRadius: 4 }}>
        <div style={{ height: 4, width: `${pct}%`, background: color, borderRadius: 4, transition: "width 0.6s ease" }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 3 }}>
        <span style={{ fontSize: 10, color: "#94a3b8" }}>₹{remaining}L left</span>
        <span style={{ fontSize: 10, color: "#64748b" }}>{pct}%</span>
      </div>
    </div>
  );
}

function TeamCard({ team, isHuman, isHighBidder, isSelected, onClick }) {
  const rtmCards = team.rtm_cards || 0;
  return (
    <div onClick={onClick} style={{
      background: isSelected ? "rgba(255,255,255,0.1)" : isHuman ? "rgba(99,102,241,0.12)" : "rgba(255,255,255,0.04)",
      border: `1px solid ${isSelected ? "#fff" : isHighBidder ? "#f59e0b" : isHuman ? "#6366f1" : "rgba(255,255,255,0.08)"}`,
      borderRadius: 10, padding: "10px 12px", position: "relative",
      transition: "all 0.2s", cursor: "pointer"
    }}>
      {isHighBidder && (
        <div style={{
          position: "absolute", top: -8, right: 8,
          background: "#f59e0b", color: "#000", fontSize: 9, fontWeight: 700,
          padding: "1px 7px", borderRadius: 20, letterSpacing: "0.06em"
        }}>LEADING</div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <div style={{
          width: 28, height: 28, borderRadius: "50%",
          background: team.color || "#334155",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 9, fontWeight: 700, color: "#fff", flexShrink: 0,
          border: "1.5px solid rgba(255,255,255,0.15)"
        }}>{team.short}</div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#f1f5f9", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{team.name}</div>
          <div style={{ fontSize: 10, color: "#64748b" }}>{team.players?.length || 0} players</div>
        </div>
        {rtmCards > 0 && (
          <div style={{
            background: "rgba(168,85,247,0.15)", border: "1px solid rgba(168,85,247,0.3)",
            borderRadius: 6, padding: "2px 7px", display: "flex", alignItems: "center", gap: 3, flexShrink: 0
          }}>
            <span style={{ fontSize: 11 }}>🃏</span>
            <span style={{ fontSize: 10, fontWeight: 700, color: "#c084fc" }}>{rtmCards}</span>
          </div>
        )}
      </div>
      <BudgetBar remaining={team.budget_remaining} total={team.budget_total} />
    </div>
  );
}

function PlayerCard({ player, isLive = false }) {
  if (!player) return null;
  const prevTeam = player.previous_team && player.previous_team !== "unsold" ? player.previous_team : null;
  return (
    <div style={{
      background: isLive ? "rgba(99,102,241,0.08)" : "rgba(255,255,255,0.03)",
      border: `1px solid ${isLive ? "#6366f1" : "rgba(255,255,255,0.06)"}`,
      borderRadius: 10, padding: "10px 14px",
      display: "flex", alignItems: "center", gap: 12
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: "50%", flexShrink: 0,
        background: ROLE_COLOR[player.role] + "33",
        border: `2px solid ${ROLE_COLOR[player.role]}66`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 13, fontWeight: 700, color: ROLE_COLOR[player.role]
      }}>{player.name?.split(" ").map(w => w[0]).join("").slice(0, 2)}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#f1f5f9" }}>{player.name}</div>
        <div style={{ display: "flex", gap: 6, marginTop: 3, alignItems: "center", flexWrap: "wrap" }}>
          <Badge role={player.role} />
          {player.country && <span style={{ fontSize: 10, color: "#64748b" }}>{player.country}</span>}
          {prevTeam && <span style={{ fontSize: 10, color: "#c084fc", background: "rgba(168,85,247,0.12)", padding: "1px 7px", borderRadius: 20, border: "1px solid rgba(168,85,247,0.25)" }}>ex-{prevTeam}</span>}
          {player.specialist_tags?.slice(0, 2).map(t => (
            <span key={t} style={{ fontSize: 10, color: "#6366f1", background: "rgba(99,102,241,0.1)", padding: "1px 6px", borderRadius: 20 }}>{t}</span>
          ))}
        </div>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 11, color: "#64748b" }}>Base</div>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#e2e8f0" }}>₹{player.base_price}L</div>
      </div>
    </div>
  );
}

function FeedItem({ item }) {
  const colors = { sold: "#22c55e", bid: "#f59e0b", unsold: "#ef4444", info: "#94a3b8" };
  const color = colors[item.type] || colors.info;
  return (
    <div style={{ display: "flex", gap: 10, padding: "7px 0", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
      <div style={{ width: 3, background: color, borderRadius: 4, flexShrink: 0, alignSelf: "stretch" }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, color: "#e2e8f0" }}>{item.text}</div>
        <div style={{ fontSize: 10, color: "#475569", marginTop: 2 }}>{item.time}</div>
      </div>
    </div>
  );
}

function LiveBidPanel({ auction, onBid, onPass, humanTeam, teams, onToggleSpeed }) {
  const [customBid, setCustomBid] = useState("");
  const player = auction?.current_player;
  const currentBid = auction?.current_bid || 0;
  const leadingTeam = auction?.current_bid_team;
  const isHumanTurn = auction?.human_action_pending && humanTeam;
  const nextBid = auction?.next_bid || (currentBid ? Math.round(currentBid * 1.1) : player?.base_price || 0);
  const speed = auction?.speed || "normal";

  const speedButton = !humanTeam ? (
    <button onClick={onToggleSpeed} style={{
      background: speed === "fast" ? "rgba(245,158,11,0.2)" : "rgba(255,255,255,0.05)",
      border: `1px solid ${speed === "fast" ? "rgba(245,158,11,0.4)" : "rgba(255,255,255,0.1)"}`,
      color: speed === "fast" ? "#fcd34d" : "#94a3b8",
      padding: "4px 10px", borderRadius: 12, fontSize: 11, fontWeight: 700, cursor: "pointer",
      display: "flex", alignItems: "center", gap: 4
    }}>
      {speed === "fast" ? "⏪ Normal Speed" : "⏩ Fast Forward"}
    </button>
  ) : null;

  if (!player) return (
    <div style={{ textAlign: "center", padding: "40px 20px", color: "#475569" }}>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>{speedButton}</div>
      <div style={{ fontSize: 32, marginBottom: 8 }}>🏏</div>
      <div style={{ fontSize: 14 }}>Waiting for next player…</div>
    </div>
  );

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <div style={{ fontSize: 11, color: "#6366f1", fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            {isHumanTurn ? "⚡ Your Turn" : " Live Now"}
          </div>
          {speedButton}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div style={{
            width: 52, height: 52, borderRadius: "50%", flexShrink: 0,
            background: ROLE_COLOR[player.role] + "33",
            border: `3px solid ${ROLE_COLOR[player.role]}`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 18, fontWeight: 800, color: ROLE_COLOR[player.role]
          }}>{player.name?.split(" ").map(w => w[0]).join("").slice(0, 2)}</div>
          <div>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#f8fafc" }}>{player.name}</div>
            <div style={{ display: "flex", gap: 8, marginTop: 4, alignItems: "center", flexWrap: "wrap" }}>
              <Badge role={player.role} />
              {player.country && <span style={{ fontSize: 11, color: "#64748b" }}>{player.country}</span>}
              {player.previous_team && player.previous_team !== "unsold" && (
                <span style={{
                  fontSize: 10, color: "#c084fc", background: "rgba(168,85,247,0.15)",
                  padding: "2px 8px", borderRadius: 20, border: "1px solid rgba(168,85,247,0.3)",
                  fontWeight: 600
                }}>ex-{player.previous_team} · RTM eligible</span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
        <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "10px 14px" }}>
          <div style={{ fontSize: 10, color: "#64748b", marginBottom: 2 }}>Base Price</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: "#e2e8f0" }}>₹{player.base_price}L</div>
        </div>
        <div style={{ background: "rgba(245,158,11,0.1)", border: "1px solid rgba(245,158,11,0.2)", borderRadius: 8, padding: "10px 14px" }}>
          <div style={{ fontSize: 10, color: "#b45309", marginBottom: 2 }}>
            {currentBid > 0 ? `${leadingTeam || "?"} leads` : "Current Bid"}
          </div>
          <div style={{ fontSize: 22, fontWeight: 800, color: "#f59e0b" }}>
            {currentBid > 0 ? `₹${currentBid}L` : "—"}
          </div>
        </div>
      </div>

      {player.specialist_tags?.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
          {player.specialist_tags.map(t => (
            <span key={t} style={{ fontSize: 11, color: "#818cf8", background: "rgba(99,102,241,0.12)", padding: "3px 10px", borderRadius: 20 }}>{t}</span>
          ))}
        </div>
      )}

      {isHumanTurn && (
        <div style={{ borderTop: "1px solid rgba(99,102,241,0.3)", paddingTop: 14, marginTop: 4 }}>
          <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 10 }}>Your decision as <b style={{ color: "#a5b4fc" }}>{humanTeam}</b></div>
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <button onClick={() => onBid(nextBid)} style={{
              flex: 1, padding: "10px 0", background: "linear-gradient(135deg,#4f46e5,#6366f1)",
              border: "none", borderRadius: 8, color: "#fff", fontSize: 14, fontWeight: 700, cursor: "pointer"
            }}>Bid ₹{nextBid}L</button>
            <button onClick={onPass} style={{
              flex: 1, padding: "10px 0", background: "rgba(239,68,68,0.12)",
              border: "1px solid rgba(239,68,68,0.3)", borderRadius: 8, color: "#ef4444",
              fontSize: 14, fontWeight: 700, cursor: "pointer"
            }}>Pass</button>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              type="number" placeholder="Custom amount (L)"
              value={customBid} onChange={e => setCustomBid(e.target.value)}
              style={{
                flex: 1, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: 8, padding: "8px 12px", color: "#f1f5f9", fontSize: 13, outline: "none"
              }}
            />
            <button onClick={() => { if (customBid) { onBid(parseInt(customBid)); setCustomBid(""); } }}
              style={{
                padding: "8px 16px", background: "rgba(99,102,241,0.2)", border: "1px solid rgba(99,102,241,0.4)",
                borderRadius: 8, color: "#a5b4fc", fontSize: 13, fontWeight: 600, cursor: "pointer"
              }}>Custom</button>
          </div>
        </div>
      )}
    </div>
  );
}

function SummaryView({ teams }) {
  if (!teams?.length) return <div style={{ color: "#64748b", textAlign: "center", padding: 40 }}>No summary yet.</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {teams.map(t => {
        const role_breakdown = {};
        (t.players || []).forEach(p => {
          role_breakdown[p.role] = (role_breakdown[p.role] || 0) + 1;
        });

        return (
          <div key={t.name} style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 10, padding: "12px 16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#f1f5f9" }}>{t.name}</div>
              <div style={{ fontSize: 12, color: "#22c55e", fontWeight: 600 }}>₹{t.budget_remaining}L left</div>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {Object.entries(role_breakdown).map(([role, count]) => count > 0 && (
                <span key={role} style={{
                  fontSize: 11, fontWeight: 600, padding: "2px 9px", borderRadius: 20,
                  background: ROLE_COLOR[role] + "22", color: ROLE_COLOR[role], border: `1px solid ${ROLE_COLOR[role]}44`
                }}>{count} {ROLE_LABEL[role]}{count > 1 ? "s" : ""}</span>
              ))}
            </div>
            <div style={{ marginTop: 8, fontSize: 11, color: "#475569" }}>
              Spent: ₹{t.budget_total - t.budget_remaining}L &nbsp;·&nbsp; {t.players?.length || 0} players signed
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function App() {
  const [state, setState] = useState(null);
  const [feed, setFeed] = useState([]);
  const [tab, setTab] = useState("live");  // live | teams | queue | summary
  const [humanTeam, setHumanTeam] = useState("");
  const [selectedTeam, setSelectedTeam] = useState("");
  const [setupMode, setSetupMode] = useState(true);
  const feedRef = useRef(null);

  const handleWsMessage = useCallback((msg) => {
    if (msg.type === "state_snapshot") {
      setState(msg.data);
      if (msg.data.feed) setFeed(msg.data.feed);
    } else if (msg.type === "auction_started") {
      setSetupMode(false);
    } else if (msg.type === "bid_placed" || msg.type === "player_sold" || msg.type === "player_unsold" || msg.type === "rtm_exercised") {
      setState(prev => ({ ...prev, auction: { ...prev?.auction, ...msg } }));
      if (msg.text) {
        setFeed(prev => [{ time: new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }), text: msg.text, type: msg.event_type || "info" }, ...prev]);
      }
    } else if (msg.type === "speed_changed") {
      setState(prev => ({ ...prev, auction: { ...prev?.auction, speed: msg.speed } }));
    } else if (msg.type === "auction_paused" || msg.type === "auction_resumed") {
      setState(prev => ({ ...prev, auction: { ...prev?.auction, status: msg.type === "auction_paused" ? "paused" : "running" } }));
    } else if (msg.type === "auction_finished") {
      setState(prev => ({ ...prev, auction: { ...prev?.auction, status: "finished" } }));
    } else if (msg.type === "human_decision_needed") {
      setState(prev => ({ ...prev, auction: { ...prev?.auction, human_action_pending: true } }));
    }
  }, []);

  const wsConnected = useWebSocket(handleWsMessage);

  useEffect(() => {
    fetch(`${API}/state`).then(r => r.json()).then(data => {
      setState(data);
      if (data.feed) setFeed(data.feed);
    }).catch(() => { });
  }, []);


  const startAuction = async () => {
    await fetch(`${API}/auction/start`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ human_team: humanTeam || null })
    });
    setSetupMode(false);
  };

  const toggleSpeed = async () => {
    const newSpeed = state?.auction?.speed === "fast" ? "normal" : "fast";
    await fetch(`${API}/auction/speed`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speed: newSpeed })
    });
  };

  const sendHumanAction = async (action, amount) => {
    await fetch(`${API}/auction/human-action`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, amount })
    });
  };

  const teams = state?.teams || [];
  const remaining = state?.players_remaining || [];
  const auction = state?.auction || {};
  const status = auction.status || "idle";

  const downloadFeed = () => {
    const rows = [["Time", "Type", "Text"]];
    feed.forEach(item => rows.push([item.time || "", item.type || "", `"${(item.text || "").replace(/"/g, '""')}"`]));
    downloadCSV("auction_feed.csv", rows);
  };

  const downloadSoldPlayers = () => {
    const rows = [["Name", "Role", "Team", "Price (Lakhs)"]];
    (state?.players_sold || []).forEach(p => rows.push([`"${(p.name || "").replace(/"/g, '""')}"`, p.role, `"${(p.sold_to || "").replace(/"/g, '""')}"`, p.sold_price]));
    downloadCSV("sold_players.csv", rows);
  };

  const downloadTeams = () => {
    const rows = [["Team", "Player Name", "Role", "Price (Lakhs)"]];
    teams.forEach(t => {
      (t.players || []).forEach(p => {
        rows.push([`"${(t.name || "").replace(/"/g, '""')}"`, `"${(p.name || "").replace(/"/g, '""')}"`, p.role, p.price]);
      });
    });
    downloadCSV("teams_squads.csv", rows);
  };

  const downloadUnsold = () => {
    const rows = [["Name", "Role", "Base Price (Lakhs)", "Tier", "Nationality"]];
    remaining.forEach(p => rows.push([`"${(p.name || "").replace(/"/g, '""')}"`, p.role, p.base_price, p.tier, p.nationality]));
    downloadCSV(status === "finished" ? "unsold_players.csv" : "remaining_players.csv", rows);
  };

  const TABS = [
    { id: "live", label: "Live" },
    { id: "teams", label: "Teams" },
    { id: "queue", label: "Queue" },
    { id: "summary", label: "Summary" },
  ];

  const activeTeamForSquad = selectedTeam || auction.human_team;

  return (
    <div style={{
      minHeight: "100vh", background: "#0a0f1e",
      color: "#e2e8f0", fontFamily: "'DM Sans', 'Segoe UI', sans-serif",
      display: "flex", flexDirection: "column"
    }}>
      {/* Header */}
      <header style={{
        background: "rgba(15,23,42,0.95)", backdropFilter: "blur(12px)",
        borderBottom: "1px solid rgba(255,255,255,0.07)",
        padding: "0 24px", height: 56, display: "flex", alignItems: "center", gap: 16,
        position: "sticky", top: 0, zIndex: 100
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ fontSize: 22 }}></div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 800, color: "#f8fafc", letterSpacing: "-0.02em" }}>IPL Auction</div>
            <div style={{ fontSize: 10, color: "#475569", letterSpacing: "0.08em" }}>SIMULATOR 2025</div>
          </div>
        </div>

        <div style={{ flex: 1 }} />

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 8, height: 8, borderRadius: "50%",
            background: wsConnected ? "#22c55e" : "#ef4444",
            boxShadow: wsConnected ? "0 0 6px #22c55e" : "none"
          }} />
          <span style={{ fontSize: 11, color: "#64748b" }}>{wsConnected ? "Live" : "Offline"}</span>
        </div>

        {!setupMode && (
          <div style={{
            fontSize: 11, fontWeight: 700, padding: "4px 12px", borderRadius: 20,
            background: status === "running" ? "rgba(34,197,94,0.15)" : "rgba(100,116,139,0.15)",
            color: status === "running" ? "#22c55e" : "#94a3b8",
            border: `1px solid ${status === "running" ? "rgba(34,197,94,0.3)" : "rgba(100,116,139,0.2)"}`,
            letterSpacing: "0.06em", textTransform: "uppercase"
          }}>{status}</div>
        )}
      </header>

      {/* Setup overlay */}
      {setupMode && (
        <div style={{
          flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 24
        }}>
          <div style={{
            background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 16, padding: "40px 48px", maxWidth: 440, width: "100%", textAlign: "center"
          }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}></div>
            <div style={{ fontSize: 26, fontWeight: 800, color: "#f8fafc", marginBottom: 8 }}>IPL Auction 2025</div>
            <div style={{ fontSize: 14, color: "#64748b", marginBottom: 32 }}>221 players · 10 teams · ₹1200L budget each</div>

            <div style={{ marginBottom: 20, textAlign: "left" }}>
              <label style={{ fontSize: 12, color: "#94a3b8", display: "block", marginBottom: 6 }}>Play as a team (optional)</label>
              <select
                value={humanTeam} onChange={e => setHumanTeam(e.target.value)}
                style={{
                  width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)",
                  borderRadius: 8, padding: "10px 12px", color: "#f1f5f9", fontSize: 14, outline: "none"
                }}
              >
                <option value="">Watch only (spectator)</option>
                {["Mumbai Indians", "Chennai Super Kings", "Royal Challengers Bangalore", "Kolkata Knight Riders",
                  "Delhi Capitals", "Rajasthan Royals", "Sunrisers Hyderabad", "Punjab Kings", "Gujarat Titans", "Lucknow Super Giants"
                ].map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>

            <button onClick={startAuction} style={{
              width: "100%", padding: "13px 0",
              background: "linear-gradient(135deg, #4f46e5, #7c3aed)",
              border: "none", borderRadius: 10, color: "#fff",
              fontSize: 16, fontWeight: 700, cursor: "pointer", letterSpacing: "-0.01em"
            }}>Start Auction →</button>
          </div>
        </div>
      )}

      {/* Main layout */}
      {!setupMode && (
        <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
          {/* Left: Live bid + feed */}
          <div style={{
            width: 340, flexShrink: 0, borderRight: "1px solid rgba(255,255,255,0.07)",
            display: "flex", flexDirection: "column", overflow: "hidden"
          }}>
            <div style={{ padding: "16px 16px 12px", borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
              <LiveBidPanel
                auction={auction}
                humanTeam={humanTeam || null}
                teams={teams}
                onBid={(amt) => sendHumanAction("bid", amt)}
                onPass={() => sendHumanAction("pass")}
                onToggleSpeed={toggleSpeed}
              />
            </div>

            {/* Feed */}
            <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
              <div style={{ padding: "10px 16px 6px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 11, color: "#475569", fontWeight: 600, letterSpacing: "0.07em" }}>AUCTION FEED</span>
                <button onClick={downloadFeed} style={{ background: "none", border: "1px solid #475569", color: "#94a3b8", borderRadius: 4, padding: "2px 6px", fontSize: 10, cursor: "pointer" }}>CSV</button>
              </div>
              <div ref={feedRef} style={{ flex: 1, overflowY: "auto", padding: "0 16px 16px" }}>
                {feed.length === 0 && <div style={{ color: "#334155", fontSize: 12, paddingTop: 8 }}>Feed will appear here…</div>}
                {feed.slice(0, 50).map((item, i) => <FeedItem key={i} item={item} />)}
              </div>
            </div>
          </div>

          {/* Right: tabbed panel */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {/* Tabs */}
            <div style={{
              display: "flex", borderBottom: "1px solid rgba(255,255,255,0.07)",
              padding: "0 20px", gap: 4
            }}>
              {TABS.map(t => (
                <button key={t.id} onClick={() => setTab(t.id)} style={{
                  padding: "14px 16px", background: "none",
                  border: "none", borderBottom: `2px solid ${tab === t.id ? "#6366f1" : "transparent"}`,
                  color: tab === t.id ? "#a5b4fc" : "#64748b",
                  fontSize: 13, fontWeight: tab === t.id ? 700 : 400, cursor: "pointer",
                  transition: "color 0.2s"
                }}>{t.id === "queue" && status === "finished" ? "Unsold" : t.label}</button>
              ))}
            </div>

            <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
              {/* Teams tab */}
              {tab === "teams" && (
                <div>
                  <div style={{ fontSize: 12, color: "#475569", marginBottom: 14, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>{teams.length} franchises · Budget tracker</span>
                    <button onClick={downloadTeams} style={{ background: "none", border: "1px solid #475569", color: "#94a3b8", borderRadius: 4, padding: "2px 6px", fontSize: 10, cursor: "pointer" }}>Download Squads CSV</button>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
                    {teams.map(t => (
                      <TeamCard
                        key={t.name} team={t}
                        isHuman={t.name === auction.human_team}
                        isHighBidder={t.short === auction.current_bid_team}
                        isSelected={t.name === activeTeamForSquad}
                        onClick={() => setSelectedTeam(t.name)}
                      />
                    ))}
                  </div>

                  {/* Expanded squad for active team */}
                  {activeTeamForSquad && (
                    <div style={{ marginTop: 28 }}>
                      <div style={{ fontSize: 12, color: "#6366f1", fontWeight: 600, letterSpacing: "0.07em", marginBottom: 12 }}>SQUAD — {activeTeamForSquad}</div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 8 }}>
                        {(teams.find(t => t.name === activeTeamForSquad)?.players || []).map((p, i) => (
                          <div key={i} style={{
                            display: "flex", alignItems: "center", gap: 12,
                            background: "rgba(99,102,241,0.06)", border: "1px solid rgba(99,102,241,0.15)",
                            borderRadius: 8, padding: "8px 12px"
                          }}>
                            <Badge role={p.role} />
                            <span style={{ fontSize: 13, color: "#e2e8f0", flex: 1 }}>{p.name}</span>
                            <span style={{ fontSize: 12, color: "#f59e0b", fontWeight: 600 }}>₹{p.price}L</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Queue tab */}
              {tab === "queue" && (
                <div>
                  <div style={{ fontSize: 12, color: "#475569", marginBottom: 14, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>{remaining.length} {status === "finished" ? "unsold players" : "players remaining in auction"}</span>
                    <button onClick={downloadUnsold} style={{ background: "none", border: "1px solid #475569", color: "#94a3b8", borderRadius: 4, padding: "2px 6px", fontSize: 10, cursor: "pointer" }}>Download CSV</button>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {remaining.map((p, i) => (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ fontSize: 11, color: "#334155", width: 22, textAlign: "right", flexShrink: 0 }}>#{i + 1}</div>
                        <div style={{ flex: 1 }}><PlayerCard player={p} /></div>
                      </div>
                    ))}
                    {remaining.length === 0 && <div style={{ color: "#475569", fontSize: 13 }}>All players have been auctioned.</div>}
                  </div>
                </div>
              )}

              {/* Live tab (right panel when not in left column view) */}
              {tab === "live" && (
                <div>
                  <div style={{ fontSize: 12, color: "#475569", marginBottom: 14, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>Sold players</span>
                    <button onClick={downloadSoldPlayers} style={{ background: "none", border: "1px solid #475569", color: "#94a3b8", borderRadius: 4, padding: "2px 6px", fontSize: 10, cursor: "pointer" }}>Download CSV</button>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {(state?.players_sold || []).map((p, i) => (
                      <div key={i} style={{
                        display: "flex", alignItems: "center", gap: 12,
                        background: "rgba(34,197,94,0.05)", border: "1px solid rgba(34,197,94,0.12)",
                        borderRadius: 8, padding: "9px 14px"
                      }}>
                        <Badge role={p.role} />
                        <span style={{ fontSize: 13, color: "#e2e8f0", flex: 1 }}>{p.name}</span>
                        <span style={{ fontSize: 11, color: "#64748b" }}>{p.sold_to}</span>
                        <span style={{ fontSize: 13, fontWeight: 700, color: "#22c55e" }}>₹{p.sold_price}L</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Summary tab */}
              {tab === "summary" && <SummaryView teams={teams} />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}