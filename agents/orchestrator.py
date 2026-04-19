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
        if self.snapshot_cb:
            self.snapshot_cb()

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
                if not test_mode:
                    speed = self.get_speed_cb() if self.get_speed_cb else "normal"
                    time.sleep(0.2 if speed == "normal" else 0.05)
                continue

            if len(active) == 1 and state.highest_bidder == active[0]:
                # --- HAMMER WARNING STATE MACHINE ---
                # Going Once → Going Twice → SOLD!
                is_spectator = self.human_team_id is None
                speed = self.get_speed_cb() if self.get_speed_cb else "normal"
                skip_warnings = is_spectator and speed == "fast"
                hammer_delay = self._get_hammer_delay() if not skip_warnings else 0

                if not skip_warnings and state.hammer_state == "active":
                    state.hammer_state = "going_once"
                    if self.broadcast_cb:
                        self.broadcast_cb({
                            "type": "hammer_warning", "stage": "going_once",
                            "player": player.name,
                            "current_bid": round(current_bid / 100000),
                            "current_leader": state.highest_bidder,
                            "text": f"⚠️ GOING ONCE... {player.name} at ₹{round(current_bid / 100000)}L to {state.highest_bidder}",
                            "event_type": "info"
                        })
                    if self.snapshot_cb:
                        self.snapshot_cb()
                    if not test_mode and hammer_delay > 0:
                        time.sleep(hammer_delay)
                    continue  # Loop back — give teams a chance to jump in

                if not skip_warnings and state.hammer_state == "going_once":
                    state.hammer_state = "going_twice"
                    if self.broadcast_cb:
                        self.broadcast_cb({
                            "type": "hammer_warning", "stage": "going_twice",
                            "player": player.name,
                            "current_bid": round(current_bid / 100000),
                            "current_leader": state.highest_bidder,
                            "text": f"⚠️ GOING TWICE... {player.name} at ₹{round(current_bid / 100000)}L to {state.highest_bidder}",
                            "event_type": "info"
                        })
                    if self.snapshot_cb:
                        self.snapshot_cb()
                    if not test_mode and hammer_delay > 0:
                        time.sleep(hammer_delay)
                    continue  # One more chance

                # SOLD! (or skip_warnings or already went through both warnings)
                state.hammer_state = "active"  # Reset for next player
                # --- RTM FINAL RAISE LOGIC ---
                resolved_bid = current_bid
                rtm_team_id = state.rtm_history.get(player.name)
                if rtm_team_id and rtm_team_id != state.highest_bidder:
                    resolved_bid = self._resolve_rtm(
                        player, state.highest_bidder, rtm_team_id,
                        current_bid, state, test_mode
                    )
                # ---------------------
                
                final_price = resolved_bid
                self.engine.state.current_bid = final_price
                print(f"[SOLD] {player.name} sold to {state.highest_bidder} for {final_price}.")
                if self.broadcast_cb:
                    self.broadcast_cb({
                        "type": "player_sold",
                        "player": player.name,
                        "team": state.highest_bidder,
                        "price": round(final_price / 100000),
                        "text": f"{player.name} SOLD to {state.highest_bidder} for ₹{round(final_price / 100000)}L" + (" (Accelerated)" if state.is_accelerated_phase else ""),
                        "event_type": "sold"
                    })
                # Notify all OTHER teams they lost this target (compensatory escalation)
                for tid, agent in self.team_agents.items():
                    if tid != state.highest_bidder:
                        agent.record_lost_target(player.name, player.role)
                self.engine.next_player()
                self.memory.update_scarcity_index(
                    self.engine.state.unsold_players,
                    self.engine.state.unsold_players + self.engine.state.sold_players
                )
                # --- DESPERATION CRISIS SCAN ---
                self._scan_for_desperation_crisis()
                if self.snapshot_cb:
                    self.snapshot_cb()
                if not test_mode:
                    speed = self.get_speed_cb() if self.get_speed_cb else "normal"
                    time.sleep(0.5 if speed == "normal" else 0.1)
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

                # --- RTM STRATEGIC AUTO-PASS ---
                # If this team holds RTM for the current player and someone else
                # has already bid, there's no reason to bid now — they'd only be
                # driving the price up against themselves.  They can exercise RTM
                # at whatever the final hammer price turns out to be.
                # Exception: if nobody has bid yet (highest_bidder is None), the
                # RTM team should still open bidding to prevent their target from
                # going unsold.
                rtm_holder = state.rtm_history.get(player.name)
                if (rtm_holder == current_team_id
                        and agent.team.rtm_cards > 0
                        and state.highest_bidder is not None):
                    self._log_test(test_mode, f"{current_team_id} RTM Hold",
                                   f"Sitting out — holds RTM for {player.name}, will decide at hammer price.")
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
        
        # Human team shortlist — if human is playing, pause and let them pick
        if self.human_team_id:
            import backend.main as main_module
            # Send unsold player list to frontend for selection
            unsold_data = [{"name": p.name, "role": p.role, "base_price": round(p.base_price / 100000),
                           "specialist_tags": p.specialist_tags} for p in unsold_pool]
            main_module.sync_broadcast({
                "type": "accelerated_phase_pending",
                "unsold_players": unsold_data,
                "max_selections": 5
            })
            main_module.send_state_snapshot()
            # Wait for human to submit their shortlist
            main_module.accelerated_shortlist_event.wait()
            main_module.accelerated_shortlist_event.clear()
            human_names = main_module.accelerated_shortlist_value or []
            shortlisted_names.update(human_names)
            print(f"  HUMAN shortlists: {human_names}")
        else:
            # Spectator mode — auto-pick top 5 by brand value
            auto_picks = sorted(unsold_pool, key=lambda p: (-p.brand_value, -p.recent_form))[:5]
            shortlisted_names.update(p.name for p in auto_picks)

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
            # Reset hammer warnings — a new bid means we restart the sequence
            self.engine.state.hammer_state = "active"
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
                # Increased minimum delay to 0.05s to prevent WebSocket flooding and RAM spikes
                delay = 1.2 if speed == "normal" else 0.05
                time.sleep(delay)
            
        elif resp["status"] == "ERROR":
            self._log_test(test_mode, f"[ERROR] Engine rejected {team_id}", resp["error_msg"])
            self.engine.apply_action({"action_type": "PASS", "team_id": team_id})

            
    def _log_test(self, test_mode: bool, prefix: str, data: Any):
        if test_mode:
            print(f"[{prefix}] {data}")

    def _resolve_rtm(self, player, buying_team_id: str, rtm_team_id: str,
                     hammer_price: int, state, test_mode: bool) -> int:
        """2025 IPL Final Raise RTM flow.

        1. RTM team decides to invoke RTM at hammer_price
        2. Buying team gets ONE chance to raise by one increment
        3. If raised, RTM team must match or concede
        Returns the final resolved price.
        """
        rtm_agent = self.team_agents.get(rtm_team_id)
        buying_agent = self.team_agents.get(buying_team_id)

        # Step 1: Does RTM team want to invoke?
        if not rtm_agent or not rtm_agent.should_invoke_rtm(player, hammer_price, state):
            return hammer_price  # No RTM — original sale stands

        price_l = round(hammer_price / 100000)
        self._log_test(test_mode, "RTM_INVOKED",
                       f"{rtm_team_id} invokes RTM for {player.name} at ₹{price_l}L")
        if self.broadcast_cb:
            self.broadcast_cb({
                "type": "rtm_exercised",
                "rtm_stage": "RTM_INVOKED",
                "player": player.name,
                "rtm_team": rtm_team_id,
                "buying_team": buying_team_id,
                "price": price_l,
                "text": f"🃏 RTM INVOKED! {rtm_team_id} wants to match ₹{price_l}L for {player.name}",
                "event_type": "rtm"
            })

        # Small delay so spectators can see the RTM event
        if not test_mode:
            speed = self.get_speed_cb() if self.get_speed_cb else "normal"
            time.sleep(2.0 if speed == "normal" else 0.2)

        # Step 2: Buying team gets ONE final raise
        final_raise = None
        if buying_team_id == self.human_team_id:
            # Human player decides — handled via WebSocket prompt
            final_raise = self._human_rtm_decision(
                player, hammer_price, "final_raise", buying_team_id)
        elif buying_agent:
            final_raise = buying_agent.compute_final_raise(
                player, hammer_price, state)

        if final_raise is None:
            # Buying team passes — RTM succeeds at original price
            rtm_agent.team.rtm_cards -= 1
            state.highest_bidder = rtm_team_id
            self._log_test(test_mode, "RTM_COMPLETED",
                           f"{rtm_team_id} takes {player.name} at ₹{price_l}L")
            if self.broadcast_cb:
                self.broadcast_cb({
                    "type": "rtm_exercised",
                    "rtm_stage": "RTM_COMPLETED",
                    "player": player.name,
                    "team": rtm_team_id,
                    "price": price_l,
                    "text": f"🃏 RTM COMPLETED! {rtm_team_id} takes {player.name} for ₹{price_l}L",
                    "event_type": "sold"
                })
            return hammer_price

        # Step 3: Buying team raised — RTM team must match or concede
        raise_l = round(final_raise / 100000)
        self._log_test(test_mode, "FINAL_RAISE_OFFERED",
                       f"{buying_team_id} raises to ₹{raise_l}L")
        if self.broadcast_cb:
            self.broadcast_cb({
                "type": "rtm_exercised",
                "rtm_stage": "FINAL_RAISE_OFFERED",
                "player": player.name,
                "buying_team": buying_team_id,
                "rtm_team": rtm_team_id,
                "price": raise_l,
                "text": f"⬆️ FINAL RAISE! {buying_team_id} raises to ₹{raise_l}L — {rtm_team_id} must match or concede",
                "event_type": "rtm"
            })

        if not test_mode:
            speed = self.get_speed_cb() if self.get_speed_cb else "normal"
            time.sleep(2.0 if speed == "normal" else 0.2)

        # RTM team decides to match or concede
        rtm_matches = False
        if rtm_team_id == self.human_team_id:
            match_response = self._human_rtm_decision(
                player, final_raise, "match_raise", rtm_team_id)
            rtm_matches = match_response is not None
        else:
            rtm_matches = rtm_agent.should_match_final_raise(
                player, final_raise, state)

        if rtm_matches:
            rtm_agent.team.rtm_cards -= 1
            state.highest_bidder = rtm_team_id
            state.current_bid = final_raise
            self._log_test(test_mode, "FINAL_RAISE_MATCHED",
                           f"{rtm_team_id} MATCHES ₹{raise_l}L")
            if self.broadcast_cb:
                self.broadcast_cb({
                    "type": "rtm_exercised",
                    "rtm_stage": "FINAL_RAISE_MATCHED",
                    "player": player.name,
                    "team": rtm_team_id,
                    "price": raise_l,
                    "text": f"🃏 RTM MATCHED! {rtm_team_id} matches ₹{raise_l}L for {player.name}",
                    "event_type": "sold"
                })
            return final_raise
        else:
            # RTM conceded — player stays with buying team at raised price
            state.highest_bidder = buying_team_id
            state.current_bid = final_raise
            self._log_test(test_mode, "RTM_CONCEDED",
                           f"{rtm_team_id} concedes — {buying_team_id} keeps {player.name} at ₹{raise_l}L")
            if self.broadcast_cb:
                self.broadcast_cb({
                    "type": "rtm_exercised",
                    "rtm_stage": "RTM_CONCEDED",
                    "player": player.name,
                    "team": buying_team_id,
                    "rtm_team": rtm_team_id,
                    "price": raise_l,
                    "text": f"❌ RTM CONCEDED! {rtm_team_id} backs off — {buying_team_id} keeps {player.name} at ₹{raise_l}L",
                    "event_type": "sold"
                })
            return final_raise

    def _human_rtm_decision(self, player, price: int, decision_type: str, team_id: str):
        """Pause and prompt the human player for an RTM-related decision."""
        import backend.main as main_module
        from engine.auction_engine import get_next_bid_increment

        main_module.auction_state["human_action_pending"] = True
        main_module.auction_state["rtm_decision_type"] = decision_type
        main_module.auction_state["rtm_price"] = round(price / 100000)

        if decision_type == "final_raise":
            increment = get_next_bid_increment(price)
            raise_amount = round((price + increment) / 100000)
            main_module.auction_state["rtm_raise_amount"] = raise_amount

        main_module.sync_broadcast({
            "type": "human_rtm_decision_needed",
            "decision_type": decision_type,
            "player": player.name,
            "team_id": team_id,
            "price": round(price / 100000),
        })
        main_module.send_state_snapshot()

        main_module.human_action_event.wait()
        action = main_module.human_action_value.get("action", "pass").upper()
        main_module.auction_state["human_action_pending"] = False
        main_module.auction_state.pop("rtm_decision_type", None)
        main_module.auction_state.pop("rtm_price", None)
        main_module.auction_state.pop("rtm_raise_amount", None)

        if decision_type == "final_raise" and action == "BID":
            increment = get_next_bid_increment(price)
            return price + increment
        elif decision_type == "match_raise" and action == "BID":
            return price  # match = accept at that price
        return None

    def _scan_for_desperation_crisis(self):
        """After each sale, check if any team has a critical role shortage."""
        from tools.valuation_filter import MANDATORY_ROLE_MINIMUMS
        state = self.engine.get_state()
        remaining_pool = state.unsold_players

        for t_id, team in state.teams.items():
            # Check wicket-keeper crisis specifically
            wk_count = team.roles_count.get("wicket_keeper", 0)
            wk_remaining = sum(1 for p in remaining_pool if p.role == "wicket_keeper")
            if wk_count == 0 and wk_remaining <= 3:
                crisis_msg = f"⚠️ CRISIS: {t_id} HAS NO KEEPER — {wk_remaining} remain in pool!"
                print(crisis_msg)
                self.memory.desperation_events.append({
                    "team": t_id, "role": "wicket_keeper",
                    "remaining_in_pool": wk_remaining
                })
                if self.broadcast_cb:
                    self.broadcast_cb({
                        "type": "desperation_crisis",
                        "team": t_id, "role": "WK",
                        "text": crisis_msg, "event_type": "info"
                    })

            # Check bowler crisis
            bowl_count = team.roles_count.get("bowler", 0)
            bowl_remaining = sum(1 for p in remaining_pool if p.role == "bowler")
            if bowl_count < 2 and bowl_remaining <= 5:
                self.memory.desperation_events.append({
                    "team": t_id, "role": "bowler",
                    "remaining_in_pool": bowl_remaining
                })

    def _get_hammer_delay(self) -> float:
        """Read hammer_delay_seconds from config."""
        try:
            import yaml
            with open("config/llm.yaml") as f:
                cfg = yaml.safe_load(f)
            return float(cfg.get("hammer_delay_seconds", 2))
        except Exception:
            return 2.0
