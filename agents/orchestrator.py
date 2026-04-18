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
    def __init__(self, engine: AuctionEngine, team_agents: Dict[str, TeamAgent], human_team_id: str = None, memory: MemoryStore = None, broadcast_cb=None, snapshot_cb=None, is_paused_cb=None, is_human_pending_cb=None, get_speed_cb=None):
        self.engine = engine
        self.team_agents = team_agents
        self.human_team_id = human_team_id
        self.memory = memory or MemoryStore()
        self.broadcast_cb = broadcast_cb
        self.snapshot_cb = snapshot_cb
        self.is_paused_cb = is_paused_cb
        self.is_human_pending_cb = is_human_pending_cb
        self.get_speed_cb = get_speed_cb

    def run_auction(self, test_mode: bool = False):
        print("Starting IPL Auction Simulator...")
        resp = self.engine.start_auction()
        self._log_test(test_mode, "AUCTION START", resp)

        self._run_bidding_loop(test_mode)

        # --- ACCELERATED PHASE ---
        self._run_accelerated_phase(test_mode)

        print("=== FULL AUCTION COMPLETE ===")

    def _run_bidding_loop(self, test_mode: bool = False):
        """Core bidding loop — shared between main auction and accelerated phase."""
        while True:
            if self.is_paused_cb and self.is_paused_cb():
                time.sleep(1)
                continue
                
            state = self.engine.get_state()

            if state.is_auction_complete:
                print("MAIN PHASE COMPLETE." if not state.is_accelerated_phase else "ACCELERATED PHASE COMPLETE.")
                break

            if not state.current_player:
                self.engine.next_player()
                if self.snapshot_cb:
                    self.snapshot_cb()
                continue

            player = state.current_player
            current_bid = state.current_bid
            bidding_rounds = state.bidding_rounds

            # In accelerated phase, enforce a hard round limit (simulated 60-second timer)
            if state.is_accelerated_phase and bidding_rounds >= 15:
                # Force resolve — time's up
                for t_id in list(state.active_bidders):
                    if t_id != state.highest_bidder:
                        self.engine.apply_action({"action_type": "PASS", "team_id": t_id})

            active = list(state.active_bidders)

            if len(active) == 0:
                print(f"[SOLD/UNSOLD] Resolving {player.name}...")
                if not state.highest_bidder:
                    if self.broadcast_cb:
                        self.broadcast_cb({
                            "type": "player_unsold",
                            "player": player.name,
                            "text": f"{player.name} went UNSOLD" + (" (Accelerated)" if state.is_accelerated_phase else ""),
                            "event_type": "unsold"
                        })
                self.engine.next_player()
                self.memory.update_scarcity_index(
                    self.engine.state.unsold_players,
                    self.engine.state.unsold_players + self.engine.state.sold_players
                )
                if self.snapshot_cb:
                    self.snapshot_cb()
                continue

            if len(active) == 1 and state.highest_bidder == active[0]:
                # --- RTM LOGIC ---
                rtm_team_id = state.rtm_history.get(player.name)
                if rtm_team_id and rtm_team_id != state.highest_bidder:
                    rtm_agent = self.team_agents.get(rtm_team_id)
                    if rtm_agent and rtm_agent.should_invoke_rtm(player, current_bid, state):
                        print(f"!!! RTM EXERCISED !!! {rtm_team_id} uses RTM to steal {player.name} for {current_bid}.")
                        rtm_agent.team.rtm_cards -= 1
                        state.highest_bidder = rtm_team_id
                        if self.broadcast_cb:
                            self.broadcast_cb({
                                "type": "rtm_exercised",
                                "player": player.name,
                                "team": rtm_team_id,
                                "price": round(current_bid / 100000),
                                "text": f"🃏 RTM EXERCISED! {rtm_team_id} steals {player.name} for ₹{round(current_bid / 100000)}L",
                                "event_type": "sold"
                            })
                # ---------------------
                
                print(f"[SOLD] {player.name} sold to {state.highest_bidder} for {current_bid}.")
                if self.broadcast_cb:
                    self.broadcast_cb({
                        "type": "player_sold",
                        "player": player.name,
                        "team": state.highest_bidder,
                        "price": round(current_bid / 100000),
                        "text": f"{player.name} SOLD to {state.highest_bidder} for ₹{round(current_bid / 100000)}L" + (" (Accelerated)" if state.is_accelerated_phase else ""),
                        "event_type": "sold"
                    })
                self.engine.next_player()
                self.memory.update_scarcity_index(
                    self.engine.state.unsold_players,
                    self.engine.state.unsold_players + self.engine.state.sold_players
                )
                if self.snapshot_cb:
                    self.snapshot_cb()
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
                    self._apply_and_retry(current_team_id, action.decision, test_mode, amount=getattr(action, 'amount', None))
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
                decision = agent.make_decision(
                    player, 
                    state.current_bid, 
                    scarcity, 
                    auction_progress,
                    active_bidders=active,
                    rivalry_memory=self.memory.rivalry_memory,
                    state=state
                )
                
                # Check for purse bullying override if decision was PASS
                if decision.decision == "PASS" and agent.should_price_drive(player, state.current_bid, state):
                    drive_bid = agent.compute_drive_bid(player, state.current_bid, state)
                    from engine.auction_engine import get_next_bid
                    if drive_bid >= get_next_bid(state.current_bid):
                        decision.decision = "BID"
                        decision.amount = drive_bid
                        self._log_test(test_mode, f"STRATEGIC PRICE DRIVE {current_team_id}", f"Driving price to {drive_bid}")
                        
                        # Add to memory tracking
                        if not hasattr(self.memory, 'price_drive_events'):
                            self.memory.price_drive_events = []
                        self.memory.price_drive_events.append({
                            "driver": current_team_id,
                            "target_rival": getattr(agent, "target_rival_cache", "Unknown"),
                            "player": player.name,
                            "amount": drive_bid
                        })

                self._log_test(test_mode, f"LLM Decision {current_team_id}", str(decision))
                self._apply_and_retry(current_team_id, decision.decision, test_mode, amount=getattr(decision, 'amount', None))

    def _run_accelerated_phase(self, test_mode: bool = False):
        """Accelerated phase: teams shortlist unsold players for a second chance auction."""
        state = self.engine.get_state()
        unsold_pool = list(state.truly_unsold_players)
        
        if not unsold_pool:
            print("[ACCELERATED] No unsold players to re-auction.")
            return
            
        # Check if any team still has capacity
        all_full = all(t.squad_size >= t.max_squad_size for t in state.teams.values())
        if all_full:
            print("[ACCELERATED] All squads full. Skipping accelerated phase.")
            return

        print(f"\n{'='*60}")
        print(f"  ACCELERATED PHASE — {len(unsold_pool)} unsold players available")
        print(f"{'='*60}\n")

        if self.broadcast_cb:
            self.broadcast_cb({
                "type": "phase_change",
                "phase": "accelerated",
                "text": f"⚡ ACCELERATED PHASE — {len(unsold_pool)} unsold players available for re-auction",
                "event_type": "info"
            })

        # Collect shortlists from each team
        shortlisted_names = set()
        for team_id, agent in self.team_agents.items():
            names = agent.submit_accelerated_shortlist(unsold_pool, state)
            if names:
                print(f"  {team_id} shortlists: {names}")
                shortlisted_names.update(names)
        
        # Human team shortlist — if human is playing, include top 5 unsold by brand value
        if self.human_team_id:
            human_picks = sorted(unsold_pool, key=lambda p: (-p.brand_value, -p.recent_form))[:5]
            shortlisted_names.update(p.name for p in human_picks)

        if not shortlisted_names:
            print("[ACCELERATED] No team shortlisted any player. Phase skipped.")
            return

        # Filter unsold pool to only shortlisted players
        accelerated_players = [p for p in unsold_pool if p.name in shortlisted_names]
        
        # Mark them for analytics and reset for re-entry
        for p in accelerated_players:
            p.accelerated_phase = True
            # Remove from truly_unsold so they can re-enter
            if p in state.truly_unsold_players:
                state.truly_unsold_players.remove(p)

        print(f"  {len(accelerated_players)} players re-entering auction (from {len(unsold_pool)} unsold)")

        # Re-inject into the engine at base price
        from engine.auction_engine import get_minimum_bid
        state.unsold_players = accelerated_players
        state.is_auction_complete = False
        state.is_accelerated_phase = True
        state.current_player = None

        if self.snapshot_cb:
            self.snapshot_cb()

        # Run the bidding loop again for the accelerated players
        self._run_bidding_loop(test_mode)

    def _apply_and_retry(self, team_id: str, decision: str, test_mode: bool, amount: int = None):
        action_payload = {
            "action_type": decision,
            "team_id": team_id,
            "amount": amount
        }
        current_bid_before = self.engine.state.current_bid
        resp_json = self.engine.apply_action(action_payload)
        resp = json.loads(resp_json)
        
        if resp["status"] == "OK" and decision.upper() == "BID":
            if self.broadcast_cb:
                player = self.engine.state.current_player
                new_bid = self.engine.state.current_bid
                self.broadcast_cb({
                    "type": "bid_placed",
                    "player": player.name,
                    "current_bid_team": team_id,
                    "current_bid": round(new_bid / 100000),
                    "text": f"{team_id} bids ₹{round(new_bid / 100000)}L on {player.name}",
                    "event_type": "bid",
                    "human_action_pending": self.is_human_pending_cb() if self.is_human_pending_cb else False
                })
            
            # Spectator Mode & UI Visibility Delay
            if not test_mode and team_id != self.human_team_id:
                speed = self.get_speed_cb() if self.get_speed_cb else "normal"
                delay = 1.2 if speed == "normal" else 0.0001
                time.sleep(delay)
            
        elif resp["status"] == "ERROR":
            self._log_test(test_mode, f"[ERROR] Engine rejected {team_id}", resp["error_msg"])
            self.engine.apply_action({"action_type": "PASS", "team_id": team_id})

            
    def _log_test(self, test_mode: bool, prefix: str, data: Any):
        if test_mode:
            print(f"[{prefix}] {data}")
