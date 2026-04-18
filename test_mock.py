import json
from engine.state import AuctionState, Player, Team
from engine.auction_engine import AuctionEngine
from agents.team_agent import TeamAgent
from agents.orchestrator import AuctionOrchestrator
from store.memory import MemoryStore

def build_mock_state() -> AuctionState:
    team_ids = ["MI", "CSK", "RCB", "KKR", "DC", "PBKS", "RR", "SRH", "GT", "LSG"]
    teams = {}
    for team_id in team_ids:
        teams[team_id] = Team(id=team_id, name=team_id, squad={})
    players = [Player(**p) for p in json.load(open("data/mock_players.json"))]
    return AuctionState(unsold_players=players, teams=teams)

if __name__ == "__main__":
    print("Running Mock Auction Engine Test...")
    state = build_mock_state()
    memory = MemoryStore("data/team_profiles.json")
    agents = {}
    for team_id, team in state.teams.items():
        personality = memory.get_team_personality(team_id)
        agents[team_id] = TeamAgent(team=team, personality=personality)
    orchestrator = AuctionOrchestrator(
        engine=AuctionEngine(state),
        team_agents=agents,
        memory=memory
    )
    orchestrator.run_auction(test_mode=True)
    print("\n======== FINAL MOCK SQUADS =========")
    for team_id, team in state.teams.items():
        spent = team.total_budget - team.remaining_budget
        print(f"{team_id}: Spent {spent} on {team.squad_size} players.")