import json
import time
from engine.state import AuctionState, Player, Team
from engine.auction_engine import AuctionEngine
from agents.team_agent import TeamAgent
from agents.orchestrator import AuctionOrchestrator
from store.memory import MemoryStore

def run_headless_validation():
    print("🚀 STARTING HEADLESS VALIDATION RUN...")
    
    # 1. Load Data
    memory = MemoryStore("data/team_profiles.json")
    with open("data/mock_players.json", "r") as f:
        # Load only first 60 players for speed
        raw_players = json.load(f)[:60]
        unsold_players = [Player(**p) for p in raw_players]
    
    print(f"📦 Loaded {len(unsold_players)} players and {len(memory.team_profiles)} team profiles.")

    # 2. Setup State
    initial_state = AuctionState(unsold_players=unsold_players)
    team_agents = {}
    
    TEAM_ID_MAP = {
        "MI": "Mumbai Indians", "CSK": "Chennai Super Kings", "RCB": "Royal Challengers Bangalore",
        "KKR": "Kolkata Knight Riders", "DC": "Delhi Capitals", "RR": "Rajasthan Royals",
        "SRH": "Sunrisers Hyderabad", "PBKS": "Punjab Kings", "GT": "Gujarat Titans", "LSG": "Lucknow Super Giants"
    }

    for t_id, t_prof in memory.team_profiles.items():
        team_name = TEAM_ID_MAP.get(t_id, f"{t_id} Franchise")
        team = Team(id=t_id, name=team_name)
        initial_state.teams[t_id] = team
        team_agents[t_id] = TeamAgent(team=team, personality=t_prof)

    # 3. Initialize Engine & Orchestrator
    engine = AuctionEngine(initial_state)
    
    # Simple callbacks for headless mode
    def dummy_broadcast(payload):
        if payload["type"] == "player_sold":
            pass # Print only sales for brevity
        elif payload["type"] == "accelerated_phase_pending":
            print(f"\n📢 Accelerated Phase Triggered! {len(payload['unsold_players'])} players available.")

    orch = AuctionOrchestrator(
        engine=engine,
        team_agents=team_agents,
        human_team_id=None, # Pure spectator/headless
        memory=memory,
        broadcast_cb=dummy_broadcast,
        snapshot_cb=None,
        get_speed_cb=lambda: "fast"
    )

    # 4. Run Auction
    start_time = time.time()
    orch.run_auction(test_mode=True)
    end_time = time.time()

    # 5. POST-RUN AUDIT
    print("\n" + "="*60)
    print(f"🏆 HEADLESS RUN COMPLETE in {end_time - start_time:.2f}s")
    print("="*60)

    final_state = engine.state
    success = True
    
    # Audit: Squad Sizes
    print("\n📋 SQUAD SIZE AUDIT:")
    for t_id, team in final_state.teams.items():
        status = "✅" if team.squad_size >= 18 else "❌ (UNDER MIN)"
        if team.squad_size > 25: status = "❌ (OVER MAX)"
        print(f"  - {t_id}: {team.squad_size} players {status} | Budget: ₹{team.remaining_budget/100000:.1f}L")
        if team.squad_size < 18: success = False

    # Audit: Overseas Limits
    print("\n📋 OVERSEAS LIMIT AUDIT:")
    for t_id, team in final_state.teams.items():
        overseas_count = team.overseas_slots_used
        status = "✅" if overseas_count <= 8 else "❌ (OVER LIMIT)"
        print(f"  - {t_id}: {overseas_count} overseas {status}")
        if overseas_count > 8: success = False

    # Audit: Unsold Pool
    print(f"\n📊 SUMMARY:")
    print(f"  - Total Sold: {len(final_state.sold_players)}")
    print(f"  - Total Truly Unsold: {len(final_state.truly_unsold_players)}")

    if success:
        print("\n✨ ALL REALISM CONSTRAINTS VALIDATED!")
    else:
        print("\n⚠️ VALIDATION FAILED! Check squad sizes or overseas limits.")

if __name__ == "__main__":
    run_headless_validation()
