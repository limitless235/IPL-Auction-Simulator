import json
import time
from typing import Dict, Any, List

from engine.auction_engine import AuctionEngine
from engine.state import AuctionState
from agents.team_agent import TeamAgent
from agents.human_agent import HumanAgent
from tools.valuation_filter import ValuationFilter
from store.memory import MemoryStore

class AuctionOrchestrator:
    def __init__(self, engine: AuctionEngine, team_agents: Dict[str, TeamAgent], human_team_id: str = None, memory: MemoryStore = None):
        self.engine = engine
        self.team_agents = team_agents
        self.human_team_id = human_team_id
        self.memory = memory or MemoryStore()

    def run_auction(self, test_mode: bool = False):
        print("Starting IPL Auction Simulator...")
        resp = self.engine.start_auction()
        self._log_test(test_mode, "AUCTION START", resp)

        while True:
            state = self.engine.get_state()

            if state.is_auction_complete:
                print("AUCTION COMPLETE.")
                break

            if not state.current_player:
                self.engine.next_player()
                continue

            player = state.current_player
            current_bid = state.current_bid
            bidding_rounds = state.bidding_rounds

            if bidding_rounds >= 50:
                print(f"[LIMIT EXCEEDED] Max rounds reached for {player.name}. Forcing sale.")
                self.engine.state.active_bidders = (
                    [state.highest_bidder] if state.highest_bidder else []
                )
                self.engine.next_player()
                self.memory.update_scarcity_index(
                    self.engine.state.unsold_players,
                    self.engine.state.unsold_players + self.engine.state.sold_players
                )
                continue

            active = list(state.active_bidders)

            if len(active) == 0:
                print(f"[SOLD/UNSOLD] Resolving {player.name}...")
                self.engine.next_player()
                self.memory.update_scarcity_index(
                    self.engine.state.unsold_players,
                    self.engine.state.unsold_players + self.engine.state.sold_players
                )
                continue

            if len(active) == 1 and state.highest_bidder == active[0]:
                print(f"[SOLD] {player.name} sold to {state.highest_bidder} for {current_bid}.")
                self.engine.next_player()
                self.memory.update_scarcity_index(
                    self.engine.state.unsold_players,
                    self.engine.state.unsold_players + self.engine.state.sold_players
                )
                continue

            # Full round-robin through all active bidders
            for current_team_id in active:
                state = self.engine.get_state()
                if state.is_auction_complete or not state.current_player:
                    break
                if current_team_id == state.highest_bidder:
                    continue
                if current_team_id not in state.active_bidders:
                    continue

                if current_team_id == self.human_team_id:
                    human = HumanAgent(self.human_team_id)
                    from engine.auction_engine import get_next_bid
                    next_bid = get_next_bid(state.current_bid)
                    action = human.make_decision(
                        player,
                        state.current_bid,
                        next_bid,
                        agent_team.remaining_budget if (agent_team := self.engine.state.teams.get(current_team_id)) else 0,
                        self.engine.state.teams.get(current_team_id).squad_size
                    )
                    self._apply_and_retry(current_team_id, action.decision, test_mode)
                    continue

                agent = self.team_agents.get(current_team_id)
                if not agent:
                    self.engine.apply_action({"action_type": "PASS", "team_id": current_team_id})
                    continue

                scarcity = self.memory.role_scarcity_index.get(player.role, 1.0)
                filter_tool = ValuationFilter(agent.team, player, agent.personality, scarcity)

                if filter_tool.should_auto_pass(state.current_bid):
                    self._log_test(test_mode, f"{current_team_id} Heuristic Skip", "Auto-passing due to budget/value limits.")
                    self.engine.apply_action({"action_type": "PASS", "team_id": current_team_id})
                    continue

                self._log_test(test_mode, f"{current_team_id} Calling LLM...", "")
                total_players = len(self.engine.state.unsold_players) + len(self.engine.state.sold_players) + len(self.engine.state.truly_unsold_players)
                auction_progress = len(self.engine.state.sold_players) / max(total_players, 1)
                decision = agent.make_decision(player, state.current_bid, scarcity, auction_progress)
                self._log_test(test_mode, f"LLM Decision {current_team_id}", str(decision))
                self._apply_and_retry(current_team_id, decision.decision, test_mode)

    def _apply_and_retry(self, team_id: str, decision: str, test_mode: bool):
        action_payload = {
            "action_type": decision,
            "team_id": team_id,
        }
        resp_json = self.engine.apply_action(action_payload)
        resp = json.loads(resp_json)
        if resp["status"] == "ERROR":
            self._log_test(test_mode, f"[ERROR] Engine rejected {team_id}", resp["error_msg"])
            self.engine.apply_action({"action_type": "PASS", "team_id": team_id})

            
    def _log_test(self, test_mode: bool, prefix: str, data: Any):
        if test_mode:
            print(f"[{prefix}] {data}")
