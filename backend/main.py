"""
IPL Auction Simulator — FastAPI Backend
Drop this file into your IPLAuctionSimulator/ root.
Run with: uvicorn backend.main:app --reload --port 8000
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.state import AuctionState
from engine.auction_engine import AuctionEngine
import asyncio
import json
import threading
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from store.memory import MemoryStore
from engine.state import AuctionState, Player, Team
from agents.team_agent import TeamAgent
from agents.orchestrator import AuctionOrchestrator

app = FastAPI(title="IPL Auction Simulator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory auction state (replace with your real AuctionState) ────────────
auction_state = {
    "status": "idle",          # idle | running | paused | finished
    "current_player": None,
    "current_bid": 0,
    "current_bid_team": None,
    "timer_seconds": 15,
    "human_team": None,
    "human_action_pending": False,
    "speed": "normal", # "normal" | "fast"
    "feed": [],
}

_auction_state: Optional[AuctionState] = None

ROLE_MAP = {"batter": "BAT", "bowler": "BOWL", "all_rounder": "ALL", "wicket_keeper": "WK"}

connected_clients: list[WebSocket] = []
human_action_event = threading.Event()
human_action_value: Optional[dict] = None
accelerated_shortlist_event = threading.Event()
accelerated_shortlist_value: Optional[list] = None

_main_loop = None

@app.on_event("startup")
async def on_startup():
    global _main_loop
    _main_loop = asyncio.get_running_loop()

def sync_broadcast(payload: dict):
    from datetime import datetime
    if payload.get("type") in ("bid_placed", "player_sold", "player_unsold"):
        auction_state["feed"].insert(0, {
            "time": datetime.now().strftime("%I:%M %p"),
            "text": payload.get("text", ""),
            "type": payload.get("event_type", "info")
        })
        pass # Keep all logs
    
    if _main_loop and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(payload), _main_loop)
    else:
        asyncio.run(broadcast(payload))

def send_state_snapshot():
    """Forces the frontend to do a hard refresh of the state (current_player, human_team, etc)."""
    if _main_loop and _main_loop.is_running():
        async def _send():
            snap = await get_full_state()
            await broadcast({"type": "state_snapshot", "data": snap})
        asyncio.run_coroutine_threadsafe(_send(), _main_loop)

# ── WebSocket broadcast helper ────────────────────────────────────────────────
async def broadcast(payload: dict):
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


# ── WebSocket endpoint ────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    # Send current state immediately on connect
    await ws.send_json({"type": "state_snapshot", "data": await get_full_state()})
    try:
        while True:
            await ws.receive_text()   # keep-alive; client doesn't send over WS
    except WebSocketDisconnect:
        connected_clients.remove(ws)


# ── REST: auction lifecycle ───────────────────────────────────────────────────
class StartRequest(BaseModel):
    human_team: Optional[str] = None


@app.post("/auction/start")
async def start_auction(req: StartRequest):
    global _auction_state
    if auction_state["status"] == "running":
        raise HTTPException(400, "Auction already running")

    auction_state["status"] = "running"
    auction_state["human_team"] = req.human_team
    
    # Map frontend full names to backend shorthand IDs
    TEAM_ID_MAP = {
        "Mumbai Indians": "MI",
        "Chennai Super Kings": "CSK",
        "Royal Challengers Bangalore": "RCB",
        "Kolkata Knight Riders": "KKR",
        "Delhi Capitals": "DC",
        "Rajasthan Royals": "RR",
        "Sunrisers Hyderabad": "SRH",
        "Punjab Kings": "PBKS",
        "Gujarat Titans": "GT",
        "Lucknow Super Giants": "LSG"
    }
    mapped_team_id = TEAM_ID_MAP.get(req.human_team) if req.human_team else None

    def run():
        global _auction_state
        # 1. Load data
        memory = MemoryStore("data/team_profiles.json")
        with open("data/mock_players.json", "r") as f:
            unsold_players = [Player(**p) for p in json.load(f)]

        # 2. Build state and agents
        initial_state = AuctionState(unsold_players=unsold_players)
        team_agents = {}

        for t_id, t_prof in memory.team_profiles.items():
            team_name = next((k for k, v in TEAM_ID_MAP.items() if v == t_id), f"{t_id} Franchise")
            team = Team(id=t_id, name=team_name)
            initial_state.teams[t_id] = team
            if t_id != mapped_team_id:
                team_agents[t_id] = TeamAgent(team=team, personality=t_prof)

        # 3. Build engine and orchestrator
        engine = AuctionEngine(initial_state)
        orch = AuctionOrchestrator(
            engine=engine,
            team_agents=team_agents,
            human_team_id=mapped_team_id,
            memory=memory,
            broadcast_cb=sync_broadcast,
            snapshot_cb=send_state_snapshot,
            is_paused_cb=lambda: auction_state["status"] == "paused",
            is_human_pending_cb=lambda: auction_state.get("human_action_pending", False),
            get_speed_cb=lambda: auction_state.get("speed", "normal")
        )
        
        _auction_state = engine.state
        send_state_snapshot()
        orch.run_auction(test_mode=False)
        auction_state["status"] = "finished"
        sync_broadcast({"type": "auction_finished"})

    threading.Thread(target=run, daemon=True).start()

    await broadcast({"type": "auction_started", "human_team": req.human_team})
    return {"ok": True}


@app.post("/auction/pause")
async def pause_auction():
    auction_state["status"] = "paused"
    await broadcast({"type": "auction_paused"})
    return {"ok": True}


@app.post("/auction/resume")
async def resume_auction():
    auction_state["status"] = "running"
    await broadcast({"type": "auction_resumed"})
    return {"ok": True}


class SpeedRequest(BaseModel):
    speed: str

@app.post("/auction/speed")
async def set_speed(req: SpeedRequest):
    auction_state["speed"] = req.speed
    await broadcast({"type": "speed_changed", "speed": req.speed})
    return {"ok": True}


# ── REST: human player action ─────────────────────────────────────────────────
class HumanActionRequest(BaseModel):
    action: str          # "bid" | "pass"
    amount: Optional[int] = None


@app.post("/auction/human-action")
async def human_action(req: HumanActionRequest):
    """
    Called by the frontend when the human player clicks BID or PASS.
    The orchestrator should await human_action_event instead of blocking stdin.
    """
    global human_action_value
    if not auction_state["human_action_pending"]:
        raise HTTPException(400, "No human action currently required")

    human_action_value = {"action": req.action, "amount": req.amount}
    auction_state["human_action_pending"] = False
    human_action_event.set()
    human_action_event.clear()

    await broadcast({"type": "human_action_received", "action": req.action, "amount": req.amount})
    return {"ok": True}


class AcceleratedShortlistRequest(BaseModel):
    player_names: list[str]

@app.post("/auction/accelerated-shortlist")
async def submit_accelerated_shortlist(req: AcceleratedShortlistRequest):
    """Human player submits their picks for the accelerated phase (max 5)."""
    global accelerated_shortlist_value
    if len(req.player_names) > 5:
        raise HTTPException(400, "Maximum 5 players allowed")
    accelerated_shortlist_value = req.player_names
    accelerated_shortlist_event.set()
    await broadcast({"type": "accelerated_shortlist_confirmed", "selections": req.player_names})
    return {"ok": True}


# ── REST: state queries ───────────────────────────────────────────────────────
@app.get("/state")
async def get_full_state():
    if _auction_state is None:
        return {"auction": auction_state, "teams": _stub_teams(), "players_remaining": _stub_remaining_players(), "players_sold": _stub_sold_players(), "feed": _stub_feed()}
    
    # Fill in tracking values
    if _auction_state.current_player:
        auction_state["current_player"] = _auction_state.current_player.model_dump()
        role = auction_state["current_player"].get("role", "batter")
        auction_state["current_player"]["role"] = ROLE_MAP.get(role, "BAT")
        auction_state["current_player"]["base_price"] = round(auction_state["current_player"].get("base_price", 0) / 100000)
        nat = auction_state["current_player"].get("nationality")
        auction_state["current_player"]["country"] = nat.upper() if nat else "IND"
    else:
        auction_state["current_player"] = None
    
    auction_state["current_bid"] = round(_auction_state.current_bid / 100000) if getattr(_auction_state, "current_bid", 0) else 0
    auction_state["current_bid_team"] = getattr(_auction_state, "highest_bidder", None)
    
    from engine.auction_engine import get_next_bid
    next_bid_val = get_next_bid(_auction_state.current_bid) if _auction_state.current_bid else (_auction_state.current_player.base_price if _auction_state.current_player else 0)
    auction_state["next_bid"] = round(next_bid_val / 100000)
        
    def get_sold_player_info(pid: str):
        sold_list = list(_auction_state.sold_players)
        for p in sold_list:
            if p.id == pid:
                return p.name, ROLE_MAP.get(p.role, "BAT")
        for t in _auction_state.teams.values():
            for p in t.retained_players:
                if p.id == pid:
                    return p.name, ROLE_MAP.get(p.role, "BAT")
        return pid, "BAT"
        
    def get_sold_player_details(pid: str):
        team_list = list(_auction_state.teams.items())
        for t_id, team in team_list:
            if pid in team.squad:
                return team.name, round(team.squad[pid] / 100000)
        return None, 0
        
    teams_list = list(_auction_state.teams.values())
    
    return {
        "auction": auction_state,
        "teams": [
            {
                "name": t.name,
                "short": t.id,
                "color": "#6366f1",  # Hardcoded or map it later
                "budget_total": round(t.total_budget / 100000), # in Lakhs
                "budget_remaining": round(t.remaining_budget / 100000), # in Lakhs
                "rtm_cards": getattr(t, "rtm_cards", 0),
                "players": [
                    {
                        "name": get_sold_player_info(pid)[0],
                        "role": get_sold_player_info(pid)[1],
                        "price": round(price / 100000)
                    }
                    for pid, price in list(t.squad.items())
                ]
            }
            for t in teams_list
        ],
        "players_remaining": [{"name": p.name, "role": ROLE_MAP.get(p.role, "BAT"), "base_price": round(p.base_price / 100000), "country": p.nationality.upper() if p.nationality else None, "specialist_tags": [], "previous_team": getattr(p, "previous_team", "unsold")} for p in (list(_auction_state.unsold_players) + list(_auction_state.truly_unsold_players))],
        "players_sold": [{"name": p.name, "role": ROLE_MAP.get(p.role, "BAT"), "sold_to": get_sold_player_details(p.id)[0], "sold_price": get_sold_player_details(p.id)[1], "base_price": round(p.base_price / 100000)} for p in list(_auction_state.sold_players)]
    }


@app.get("/state/teams")
async def get_teams():
    if _auction_state is None: return _stub_teams()
    return (await get_full_state())["teams"]


@app.get("/state/players/remaining")
async def get_remaining_players():
    if _auction_state is None: return _stub_remaining_players()
    return (await get_full_state())["players_remaining"]


@app.get("/state/players/sold")
async def get_sold_players():
    if _auction_state is None: return _stub_sold_players()
    return (await get_full_state())["players_sold"]


@app.get("/state/summary")
async def get_summary():
    """End-of-auction summary report."""
    if auction_state["status"] not in ("finished", "running"):
        raise HTTPException(400, "Auction not started")
        
    if _auction_state is None:
        teams = _stub_teams()
        return [
            {
                "team": t["name"],
                "budget_spent": t["budget_total"] - t["budget_remaining"],
                "budget_remaining": t["budget_remaining"],
                "players_bought": t["players"],
                "role_breakdown": _role_breakdown(t["players"]),
            }
            for t in teams
        ]
        
    summary = []
    
    def get_sold_player_info(pid: str):
        for p in _auction_state.sold_players:
            if p.id == pid:
                return {"name": p.name, "role": ROLE_MAP.get(p.role, "BAT")}
        return {"name": pid, "role": "BAT"}

    for t_id, t in _auction_state.teams.items():
        summary.append({
            "team": t.name,
            "budget_spent": round((t.total_budget - t.remaining_budget) / 100000),
            "budget_remaining": round(t.remaining_budget / 100000),
            "players_bought": [{"name": get_sold_player_info(pid)["name"], "price": round(price / 100000)} for pid, price in t.squad.items()],
            "role_breakdown": {ROLE_MAP.get(k, k): v for k, v in t.roles_count.items()},
        })
    return summary


# ── Stub data (replace with real engine reads) ────────────────────────────────
def _stub_teams():
    return [
        {"name": "Mumbai Indians", "short": "MI", "color": "#004BA0", "budget_total": 1200, "budget_remaining": 780,
         "players": [{"name": "Rohit Sharma", "role": "BAT", "price": 160}, {"name": "Jasprit Bumrah", "role": "BOWL", "price": 140}, {"name": "Hardik Pandya", "role": "ALL", "price": 120}]},
        {"name": "Chennai Super Kings", "short": "CSK", "color": "#F9CD05", "budget_total": 1200, "budget_remaining": 620,
         "players": [{"name": "MS Dhoni", "role": "WK", "price": 160}, {"name": "Ravindra Jadeja", "role": "ALL", "price": 140}]},
        {"name": "Royal Challengers Bangalore", "short": "RCB", "color": "#EC1C24", "budget_total": 1200, "budget_remaining": 900,
         "players": [{"name": "Virat Kohli", "role": "BAT", "price": 150}, {"name": "Glenn Maxwell", "role": "ALL", "price": 110}]},
        {"name": "Kolkata Knight Riders", "short": "KKR", "color": "#3A225D", "budget_total": 1200, "budget_remaining": 840,
         "players": [{"name": "Andre Russell", "role": "ALL", "price": 120}, {"name": "Sunil Narine", "role": "ALL", "price": 90}]},
        {"name": "Delhi Capitals", "short": "DC", "color": "#282968", "budget_total": 1200, "budget_remaining": 950,
         "players": [{"name": "Rishabh Pant", "role": "WK", "price": 160}]},
        {"name": "Rajasthan Royals", "short": "RR", "color": "#EA1A85", "budget_total": 1200, "budget_remaining": 860,
         "players": [{"name": "Sanju Samson", "role": "WK", "price": 140}, {"name": "Jos Buttler", "role": "BAT", "price": 130}]},
        {"name": "Sunrisers Hyderabad", "short": "SRH", "color": "#F7A721", "budget_total": 1200, "budget_remaining": 880,
         "players": [{"name": "Pat Cummins", "role": "BOWL", "price": 150}]},
        {"name": "Punjab Kings", "short": "PBKS", "color": "#DCDDDF", "budget_total": 1200, "budget_remaining": 920,
         "players": [{"name": "Shikhar Dhawan", "role": "BAT", "price": 80}]},
        {"name": "Gujarat Titans", "short": "GT", "color": "#1C1C3C", "budget_total": 1200, "budget_remaining": 810,
         "players": [{"name": "Shubman Gill", "role": "BAT", "price": 140}, {"name": "Mohammed Shami", "role": "BOWL", "price": 100}]},
        {"name": "Lucknow Super Giants", "short": "LSG", "color": "#A72056", "budget_total": 1200, "budget_remaining": 870,
         "players": [{"name": "KL Rahul", "role": "BAT", "price": 170}]},
    ]


def _stub_remaining_players():
    return [
        {"name": "Mitchell Starc", "role": "BOWL", "base_price": 200, "country": "AUS", "specialist_tags": ["pace", "death-bowling"]},
        {"name": "Sam Curran", "role": "ALL", "base_price": 185, "country": "ENG", "specialist_tags": ["swing", "batting-all-rounder"]},
        {"name": "Cameron Green", "role": "ALL", "base_price": 175, "country": "AUS", "specialist_tags": ["pace", "hard-hitting"]},
        {"name": "David Warner", "role": "BAT", "base_price": 200, "country": "AUS", "specialist_tags": ["opener"]},
        {"name": "Kagiso Rabada", "role": "BOWL", "base_price": 150, "country": "SA", "specialist_tags": ["pace", "powerplay"]},
        {"name": "Rashid Khan", "role": "BOWL", "base_price": 200, "country": "AFG", "specialist_tags": ["leg-spin", "economy"]},
    ]


def _stub_sold_players():
    return [
        {"name": "Rohit Sharma", "role": "BAT", "sold_to": "Mumbai Indians", "sold_price": 160, "base_price": 120},
        {"name": "MS Dhoni", "role": "WK", "sold_to": "Chennai Super Kings", "sold_price": 160, "base_price": 120},
        {"name": "Virat Kohli", "role": "BAT", "sold_to": "RCB", "sold_price": 150, "base_price": 150},
    ]


def _stub_feed():
    return [
        {"time": "10:42", "text": "Rohit Sharma SOLD to Mumbai Indians for ₹16 Cr", "type": "sold"},
        {"time": "10:38", "text": "MS Dhoni SOLD to CSK for ₹16 Cr", "type": "sold"},
        {"time": "10:34", "text": "Virat Kohli SOLD to RCB for ₹15 Cr", "type": "sold"},
    ]


def _role_breakdown(players):
    breakdown = {"BAT": 0, "BOWL": 0, "ALL": 0, "WK": 0}
    for p in players:
        r = p.get("role", "BAT")
        breakdown[r] = breakdown.get(r, 0) + 1
    return breakdown


def _start_stub_auction():
    """Placeholder — replace with real orchestrator threading."""
    pass