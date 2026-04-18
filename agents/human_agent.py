from typing import Optional
from engine.state import Player
from pydantic import BaseModel


class HumanDecision(BaseModel):
    decision: str  # "BID" or "PASS"
    amount: Optional[int] = None


class HumanAgent:
    def __init__(self, team_id: str):
        self.team_id = team_id

    def make_decision(self, player: Player, current_bid: int,
                      next_bid: int, remaining_budget: int,
                      squad_size: int) -> HumanDecision:
        
        import backend.main as main_module
        
        # Tell frontend we need an action
        main_module.auction_state["human_action_pending"] = True
        
        # To make sure frontend sees the state change, send a full snapshot
        # or the explicitly expected human_decision_needed event
        main_module.sync_broadcast({
            "type": "human_decision_needed", 
            "player": {"name": player.name, "role": main_module.ROLE_MAP.get(player.role, "BAT"), "base_price": round(player.base_price / 100000)}, 
            "current_bid": round(current_bid / 100000)
        })
        
        # Send a state snapshot so UI correctly interprets the human_action_pending property
        main_module.send_state_snapshot()
        
        # Wait for the user to click a button
        main_module.human_action_event.wait()
        
        action_val = main_module.human_action_value["action"].upper()
        amount_val = main_module.human_action_value.get("amount")
        if amount_val is not None:
            amount_val = amount_val * 100000
        
        return HumanDecision(decision=action_val, amount=amount_val)