import json
from typing import Dict, Any, Tuple, List
from .state import AuctionState, ActionResponse, BidAction, Player, Team

MAX_BIDDING_ROUNDS = 60


def sort_players_for_auction(players: List[Player]) -> List[Player]:
    from engine.state import Player
    seen = set()
    result = []

    def add_group(group):
        for p in group:
            if p.id not in seen:
                result.append(p)
                seen.add(p.id)

    def sort_key(p):
        return (-p.brand_value, -p.recent_form)

    def get(role=None, tier=None, nationality=None, pace=None, spin=None, tiers=None):
        out = []
        for p in players:
            if p.id in seen:
                continue
            if role and p.role != role:
                continue
            if tier and p.tier != tier:
                continue
            if tiers and p.tier not in tiers:
                continue
            if nationality and p.nationality != nationality:
                continue
            if pace is not None and p.pace_bowler != pace:
                continue
            if spin is not None and p.spin_bowler != spin:
                continue
            out.append(p)
        return sorted(out, key=sort_key)

    # Marquee sets
    add_group(get(tier=1, nationality="indian")[:6])
    add_group(get(tier=1, nationality="overseas")[:6])

    # Capped sets (tier 2)
    for role in ["batter", "all_rounder", "wicket_keeper"]:
        add_group(get(role=role, tier=2, nationality="indian"))
        add_group(get(role=role, tier=2, nationality="overseas"))

    add_group(get(role="bowler", tier=2, pace=True, nationality="indian"))
    add_group(get(role="bowler", tier=2, pace=True, nationality="overseas"))
    add_group(get(role="bowler", tier=2, spin=True, nationality="indian"))
    add_group(get(role="bowler", tier=2, spin=True, nationality="overseas"))

    # Uncapped sets (tier 3 and 4)
    for role in ["batter", "all_rounder", "wicket_keeper"]:
        add_group(get(role=role, tiers=[3, 4], nationality="indian"))
        add_group(get(role=role, tiers=[3, 4], nationality="overseas"))

    add_group(get(role="bowler", tiers=[3, 4], pace=True, nationality="indian"))
    add_group(get(role="bowler", tiers=[3, 4], pace=True, nationality="overseas"))
    add_group(get(role="bowler", tiers=[3, 4], spin=True, nationality="indian"))
    add_group(get(role="bowler", tiers=[3, 4], spin=True, nationality="overseas"))

    # Accelerated phase — anything remaining
    remaining = [p for p in players if p.id not in seen]
    add_group(sorted(remaining, key=lambda p: (p.tier, -p.brand_value)))

    return result


def get_next_bid(current_bid: int) -> int:
    if current_bid < 10000000:
        return current_bid + 500000
    elif current_bid < 20000000:
        return current_bid + 1000000
    elif current_bid < 50000000:
        return current_bid + 2000000
    elif current_bid < 100000000:
        return current_bid + 2500000
    elif current_bid < 200000000:
        return current_bid + 5000000
    else:
        return current_bid + 10000000


class AuctionEngine:
    def __init__(self, initial_state: AuctionState):
        self.state = initial_state

    def start_auction(self) -> str:
        if not self.state.unsold_players:
            self.state.is_auction_complete = True
            return self.get_state_json()

        # >>> NEW: Apply IPL auction ordering
        self.state.unsold_players = sort_players_for_auction(self.state.unsold_players)

        if not self.state.current_player:
            player = self.state.unsold_players.pop(0)
            self._setup_next_player(player)

        return self.get_state_json()

    def _setup_next_player(self, player: Player):
        self.state.current_player = player
        self.state.current_bid = player.base_price
        self.state.highest_bidder = None
        self.state.active_bidders = [
            t_id for t_id, t in self.state.teams.items()
            if t.remaining_budget >= player.base_price and t.squad_size < t.max_squad_size
        ]
        self.state.bidding_rounds = 0

    def apply_action(self, action_dict: Dict[str, Any]) -> str:
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
            return self._handle_bid(action.team_id)

        return self._format_response("ERROR", f"Unsupported action_type: {action.action_type}")

    def _handle_pass(self, team_id: str) -> str:
        if team_id in self.state.active_bidders:
            self.state.active_bidders.remove(team_id)
        return self._format_response("OK")

    def _handle_bid(self, team_id: str) -> str:
        team = self.state.teams[team_id]

        if team_id not in self.state.active_bidders:
            return self._format_response("ERROR", "Team is not an active bidder.")

        next_bid = get_next_bid(self.state.current_bid)

        if next_bid > team.remaining_budget:
            return self._format_response("ERROR", "Next bid increment exceeds remaining budget.")

        if team.squad_size >= team.max_squad_size:
            return self._format_response("ERROR", "Team squad is already full.")

        player = self.state.current_player
        if player.nationality == "overseas":
            if team.overseas_slots_used >= 4:
                return self._format_response("ERROR",
                    "Team has no overseas slots remaining.")

        self.state.highest_bidder = team_id
        self.state.current_bid = next_bid
        self.state.bidding_rounds += 1
        return self._format_response("OK")

    def next_player(self) -> str:
        if not self.state.current_player:
            return self._format_response("ERROR", "No active player to resolve.")

        player = self.state.current_player

        if self.state.highest_bidder:
            winning_team = self.state.teams[self.state.highest_bidder]
            winning_team.remaining_budget -= self.state.current_bid
            winning_team.squad[player.id] = self.state.current_bid
            winning_team.squad_size += 1
            winning_team.roles_count[player.role] += 1

            if player.nationality == "overseas":
                winning_team.overseas_slots_used += 1

            self.state.sold_players.append(player)
        else:
            self.state.truly_unsold_players.append(player)

        all_squads_full = all(t.squad_size >= t.max_squad_size for t in self.state.teams.values())
        if not self.state.unsold_players or all_squads_full:
            self.state.current_player = None
            self.state.is_auction_complete = True
            return self._format_response("OK")

        next_p = self.state.unsold_players.pop(0)
        self._setup_next_player(next_p)
        return self._format_response("OK")

    def end_auction(self) -> str:
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