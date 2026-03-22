import json
from typing import Dict, Any, Tuple
from .state import AuctionState, ActionResponse, BidAction, Player, Team
MAX_BIDDING_ROUNDS = 25
class AuctionEngine:
    def __init__(self, initial_state: AuctionState):
        self.state = initial_state

    def start_auction(self) -> str:
        """Starts the auction by setting the first player and active bidders."""
        if not self.state.unsold_players:
            self.state.is_auction_complete = True
            return self.get_state_json()
        
        # Load the next player if none is active
        if not self.state.current_player:
            player = self.state.unsold_players.pop(0)
            self._setup_next_player(player)

        return self.get_state_json()

    def _setup_next_player(self, player: Player):
        self.state.current_player = player
        self.state.current_bid = player.base_price
        self.state.highest_bidder = None
        # Only teams that have budget >= base_price and space in squad can bid initially
        self.state.active_bidders = [
            t_id for t_id, t in self.state.teams.items()
            if t.remaining_budget >= player.base_price and t.squad_size < t.max_squad_size
        ]
        self.state.bidding_rounds = 0

    def apply_action(self, action_dict: Dict[str, Any]) -> str:
        """
        Receives an action, validates it, and updates state.
        Returns a JSON string containing {"status": "OK"|"ERROR", "error_msg": ..., "state": ...}
        """
        try:
            action = BidAction(**action_dict)
        except Exception as e:
            return self._format_response("ERROR", f"Invalid action format: {str(e)}")

        team = self.state.teams.get(action.team_id)
        if not team:
            return self._format_response("ERROR", f"Unknown team: {action.team_id}")

        if self.state.is_auction_complete:
            return self._format_response("ERROR", "Auction is already complete.")

        if not self.state.current_player:
            return self._format_response("ERROR", "No active player being auctioned.")

        if action.action_type == "PASS":
            return self._handle_pass(action.team_id)

        if action.action_type == "BID":
            return self._handle_bid(action.team_id, action.bid_amount)
            
        return self._format_response("ERROR", f"Unsupported action_type: {action.action_type}")

    def _handle_pass(self, team_id: str) -> str:
        if team_id in self.state.active_bidders:
            self.state.active_bidders.remove(team_id)
        return self._format_response("OK")

    def _handle_bid(self, team_id: str, bid_amount: int) -> str:
        team = self.state.teams[team_id]
        
        if team_id not in self.state.active_bidders:
            return self._format_response("ERROR", "Team is not an active bidder for this player.")

        if bid_amount is None:
            return self._format_response("ERROR", "Bid amount is required for BID action.")

        # Validation rules
        if bid_amount <= self.state.current_bid and self.state.highest_bidder is not None:
             return self._format_response("ERROR", f"Bid must be strictly greater than current bid {self.state.current_bid}")
             
        if self.state.highest_bidder is None and bid_amount < self.state.current_bid:
             return self._format_response("ERROR", f"First bid must be >= base price {self.state.current_bid}")

        if bid_amount > team.remaining_budget:
             return self._format_response("ERROR", "Bid exceeds remaining team budget.")

        if team.squad_size >= team.max_squad_size:
             return self._format_response("ERROR", "Team squad is already full.")

        # Accept bid
        self.state.highest_bidder = team_id
        self.state.current_bid = bid_amount
        self.state.bidding_rounds += 1
        if self.state.bidding_rounds >= MAX_BIDDING_ROUNDS:
        # Force sale to current highest bidder by clearing active bidders
            self.state.active_bidders = []

        return self._format_response("OK")

    def next_player(self) -> str:
        """Resolves the current player (sold/unsold) and moves to the next."""
        if not self.state.current_player:
            return self._format_response("ERROR", "No active player to resolve.")

        player = self.state.current_player
        
        # Resolve sale
        if self.state.highest_bidder:
            winning_team = self.state.teams[self.state.highest_bidder]
            # Deduct budget & assign player
            winning_team.remaining_budget -= self.state.current_bid
            winning_team.squad[player.id] = self.state.current_bid
            winning_team.squad_size += 1
            winning_team.roles_count[player.role] += 1
            self.state.sold_players.append(player)
        else:
            # Re-queue randomly or just leave as unsold? For now, we put them at end of unsold or discard.
            # Usually they go to unsold list.
            self.state.truly_unsold_players.append(player)
 # Kept out of unsold_players list so they aren't immediately drawn again

        # Check end condition
        # Simulation priority logic: all players processed or all squads full
        all_squads_full = all(t.squad_size >= t.max_squad_size for t in self.state.teams.values())
        if not self.state.unsold_players or all_squads_full:
            self.state.current_player = None
            self.state.is_auction_complete = True
            return self._format_response("OK")

        # Setup next
        next_p = self.state.unsold_players.pop(0)
        self._setup_next_player(next_p)
        return self._format_response("OK")

    def end_auction(self) -> str:
        """Forces the auction to end."""
        self.state.is_auction_complete = True
        self.state.current_player = None
        self.state.active_bidders = []
        return self._format_response("OK")

    def get_state_json(self) -> str:
        return self.state.model_dump_json()

    def get_state(self) -> AuctionState:
        return self.state

    def _format_response(self, status: str, error_msg: str = None) -> str:
        resp = ActionResponse(status=status, error_msg=error_msg)
        
        # Dump state manually so we comply with 'Returns structured JSON only'
        # To keep payload compact for LLM context, we will output summarized state later, 
        # but the engine tool itself responds with standard JSON.
        data = {
            "status": resp.status,
            "error_msg": resp.error_msg,
            "state_summary": {
                "current_player": self.state.current_player.model_dump() if self.state.current_player else None,
                "current_bid": self.state.current_bid,
                "highest_bidder": self.state.highest_bidder,
                "active_bidders": self.state.active_bidders,
                "bidding_rounds": self.state.bidding_rounds,
                "is_auction_complete": self.state.is_auction_complete
            }
        }
        return json.dumps(data)
