import json
from typing import Dict, Any, Tuple, List
from .state import AuctionState, ActionResponse, BidAction, Player, Team

MAX_BIDDING_ROUNDS = 60


def sort_players_for_auction(players: List[Player]) -> List[Player]:
    from engine.state import Player
    seen = set()
    result = []

    def add_group(group):
        import random
        group_list = list(group)
        random.shuffle(group_list)
        for p in group_list:
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

    # Capped sets (tier 1 overflow + tier 2)
    for role in ["batter", "all_rounder", "wicket_keeper"]:
        add_group(get(role=role, tiers=[1, 2], nationality="indian"))
        add_group(get(role=role, tiers=[1, 2], nationality="overseas"))

    add_group(get(role="bowler", tiers=[1, 2], pace=True, nationality="indian"))
    add_group(get(role="bowler", tiers=[1, 2], pace=True, nationality="overseas"))
    add_group(get(role="bowler", tiers=[1, 2], spin=True, nationality="indian"))
    add_group(get(role="bowler", tiers=[1, 2], spin=True, nationality="overseas"))

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


def get_next_bid_increment(current_bid: int) -> int:
    """Return the official IPL bid increment for a given current bid (in rupees).

    The IPL uses strict slab-based increments. All slab boundaries
    below are expressed in Lakhs for clarity, but the function
    operates in raw rupees (1 Lakh = 100,000).

    Official IPL slabs:
        current_bid < ₹1 Cr  (< 100L)     → increment ₹5L
        ₹1 Cr – ₹2 Cr   (100L – 200L)     → increment ₹10L
        ₹2 Cr – ₹5 Cr   (200L – 500L)     → increment ₹20L
        ₹5 Cr – ₹10 Cr  (500L – 1000L)    → increment ₹25L
        ₹10 Cr – ₹20 Cr (1000L – 2000L)   → increment ₹50L
        ≥ ₹20 Cr        (≥ 2000L)          → increment ₹100L

    >>> get_next_bid_increment(5000000)   # 50L → 5L increment
    500000
    >>> get_next_bid_increment(10000000)  # 100L → 10L increment
    1000000
    >>> get_next_bid_increment(30000000)  # 300L → 20L increment
    2000000
    >>> get_next_bid_increment(75000000)  # 750L → 25L increment
    2500000
    >>> get_next_bid_increment(150000000) # 1500L → 50L increment
    5000000
    >>> get_next_bid_increment(250000000) # 2500L → 100L increment
    10000000
    """
    bid_in_lakhs = current_bid / 100000

    if bid_in_lakhs < 100:
        return 500000       # 5 Lakh
    elif bid_in_lakhs < 200:
        return 1000000      # 10 Lakh
    elif bid_in_lakhs < 500:
        return 2000000      # 20 Lakh
    elif bid_in_lakhs < 1000:
        return 2500000      # 25 Lakh
    elif bid_in_lakhs < 2000:
        return 5000000      # 50 Lakh
    else:
        return 10000000     # 1 Crore


def get_next_bid(current_bid: int) -> int:
    """Returns the next valid bid amount (current + increment).

    This is a convenience wrapper around get_next_bid_increment,
    kept for backward compatibility with all existing call sites.
    """
    return current_bid + get_next_bid_increment(current_bid)


def get_minimum_bid(player: Player) -> int:
    """Returns the minimum opening bid for a player.

    No player sells below ₹25 Lakhs regardless of their listed base price.
    """
    return max(player.base_price, 2500000)  # 25 Lakhs = 2,500,000


def run_retention_phase(state: AuctionState, team_profiles: dict):
    # Real IPL 2025 Retentions with exact salaries
    REAL_RETENTIONS = {
        "MI": {"Jasprit Bumrah": 180000000, "Suryakumar Yadav": 163500000, "Hardik Pandya": 163500000, "Rohit Sharma": 163000000, "Tilak Varma": 80000000},
        "CSK": {"Ruturaj Gaikwad": 180000000, "Ravindra Jadeja": 180000000, "Matheesha Pathirana": 130000000, "Shivam Dube": 120000000, "MS Dhoni": 40000000},
        "RCB": {"Virat Kohli": 210000000, "Rajat Patidar": 110000000, "Yash Dayal": 50000000},
        "SRH": {"Heinrich Klaasen": 230000000, "Pat Cummins": 180000000, "Abhishek Sharma": 140000000, "Travis Head": 140000000, "Nitish Reddy": 60000000},
        "RR": {"Sanju Samson": 180000000, "Yashasvi Jaiswal": 180000000, "Dhruv Jurel": 140000000, "Riyan Parag": 140000000, "Shimron Hetmyer": 110000000, "Sandeep Sharma": 40000000},
        "KKR": {"Rinku Singh": 130000000, "Varun Chakravarthy": 120000000, "Sunil Narine": 120000000, "Andre Russell": 120000000, "Ramandeep Singh": 40000000, "Harshit Rana": 40000000},
        "DC": {"Axar Patel": 165000000, "Kuldeep Yadav": 132500000, "Tristan Stubbs": 100000000, "Abishek Porel": 40000000},
        "PBKS": {"Shashank Singh": 55000000, "Prabhsimran Singh": 40000000},
        "LSG": {"Nicholas Pooran": 210000000, "Ravi Bishnoi": 110000000, "Mayank Yadav": 110000000, "Mohsin Khan": 40000000, "Ayush Badoni": 40000000},
        "GT": {"Rashid Khan": 180000000, "Shubman Gill": 165000000, "Sai Sudharsan": 85000000, "Rahul Tewatia": 40000000, "Shahrukh Khan": 40000000}
    }
    
    # Map all players by name for easy lookup
    players_by_name = {p.name: p for p in state.unsold_players}
    
    # Assign retained players and exact costs
    for team_id, retained_dict in REAL_RETENTIONS.items():
        team = state.teams.get(team_id)
        if not team: continue
        
        for name, cost in retained_dict.items():
            if name in players_by_name:
                p = players_by_name[name]
                # Remove from unsold
                if p in state.unsold_players:
                    state.unsold_players.remove(p)
                
                team.retained_players.append(p)
                team.squad[p.id] = cost
                team.remaining_budget -= cost
                if p.nationality == "overseas":
                    team.overseas_slots_used += 1
                team.roles_count[p.role] = team.roles_count.get(p.role, 0) + 1
                team.squad_size += 1
                
        # Assign RTM cards (max 6 total retentions + RTMs)
        total_retained = len(team.retained_players)
        team.rtm_cards = max(0, 6 - total_retained)
        
    # Populate RTM history for the remaining unsold players based on previous_team
    for p in state.unsold_players:
        if getattr(p, "previous_team", "unsold") != "unsold":
            state.rtm_history[p.name] = p.previous_team
            
    return state


class AuctionEngine:
    def __init__(self, initial_state: AuctionState):
        self.state = initial_state

    def start_auction(self) -> str:
        if not self.state.unsold_players:
            self.state.is_auction_complete = True
            return self.get_state_json()

        import json
        import os
        try:
            with open(os.path.join(os.path.dirname(__file__), "..", "data", "team_profiles.json"), "r") as f:
                profiles = json.load(f)
        except Exception:
            profiles = {}

        has_retentions = any(len(t.retained_players) > 0 for t in self.state.teams.values())
        if not has_retentions:
            self.state = run_retention_phase(self.state, profiles)

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
        MIN_BASE_PRICE = 2000000
        self.state.active_bidders = []
        for t_id, t in self.state.teams.items():
            if t.squad_size >= t.max_squad_size:
                continue
            slots_to_minimum = max(0, 15 - (t.squad_size + 1))
            required_reserve = slots_to_minimum * MIN_BASE_PRICE
            if (t.remaining_budget - required_reserve) >= player.base_price:
                self.state.active_bidders.append(t_id)
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
            return self._handle_bid(action.team_id, action.amount)

        return self._format_response("ERROR", f"Unsupported action_type: {action.action_type}")

    def _handle_pass(self, team_id: str) -> str:
        if team_id in self.state.active_bidders:
            self.state.active_bidders.remove(team_id)
        return self._format_response("OK")

    def _handle_bid(self, team_id: str, amount: int = None) -> str:
        team = self.state.teams[team_id]

        if team_id not in self.state.active_bidders:
            return self._format_response("ERROR", "Team is not an active bidder.")

        next_bid = get_next_bid(self.state.current_bid)
        if amount is not None:
            if amount < next_bid:
                return self._format_response("ERROR", f"Custom bid {amount} is less than required minimum {next_bid}.")
            actual_bid = amount
        else:
            actual_bid = next_bid

        MIN_BASE_PRICE = 2000000
        slots_to_minimum = max(0, 15 - (team.squad_size + 1))
        required_reserve = slots_to_minimum * MIN_BASE_PRICE
        if actual_bid > (team.remaining_budget - required_reserve):
            return self._format_response("ERROR", "Next bid increment exceeds effective remaining budget (reserving for playing 15).")

        if team.squad_size >= team.max_squad_size:
            return self._format_response("ERROR", "Team squad is already full.")

        player = self.state.current_player
        if player.nationality == "overseas":
            if team.overseas_slots_used >= 8:
                return self._format_response("ERROR",
                    "Team has no overseas slots remaining.")

        self.state.highest_bidder = team_id
        self.state.current_bid = actual_bid
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
            winning_team.players.append(player) # Track full player object

            if player.nationality == "overseas":
                winning_team.overseas_slots_used += 1
                
            # Overseas-locked warning
            if winning_team.overseas_xi_count() > 4 and winning_team.remaining_budget < 200000000: # 20Cr threshold
                print(f"!!! WARNING: TEAM {winning_team.id} IS OVERSEAS-LOCKED !!!")

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