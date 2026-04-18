from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field

# ---------------------------------------------------------
# CORE DOMAIN MODELS
# ---------------------------------------------------------

class Player(BaseModel):
    id: str
    name: str
    role: Literal["batter", "bowler", "all_rounder", "wicket_keeper"]
    base_price: int
    is_star: bool = False
    is_youth: bool = False
    age: int = 25
    nationality: Literal["indian", "overseas"] = "indian"
    tier: int = 3
    brand_value: float = 0.0
    recent_form: float = 0.5
    ipl_experience: int = 0
    specialist_tag: str = ""
    pace_bowler: bool = False
    spin_bowler: bool = False
    previous_team: str = "unsold"
    specialist_tags: List[str] = Field(default_factory=list)
    hype_score: float = 0.0
    accelerated_phase: bool = False


class Team(BaseModel):
    id: str
    name: str
    total_budget: int = 1200000000  # 120 Cr
    remaining_budget: int = 1200000000
    squad_size: int = 0
    max_squad_size: int = 25
    min_squad_size: int = 18
    roles_count: Dict[str, int] = Field(
        default_factory=lambda: {
            "batter": 0,
            "bowler": 0,
            "all_rounder": 0,
            "wicket_keeper": 0
        }
    )
    # Roster mapping player_id -> purchase_price
    squad: Dict[str, int] = Field(default_factory=dict)
    
    # Track full player objects
    players: List[Player] = Field(default_factory=list)
    
    overseas_slots_used: int = 0
    retained_players: List[Player] = Field(default_factory=list)
    rtm_cards: int = 0

    def overseas_xi_count(self) -> int:
        """Counts overseas players that would realistically start (tier <= 2 or brand_value >= 0.6)."""
        count = 0
        # Combine retained and bought players
        all_players = self.players + self.retained_players
        for p in all_players:
            if p.nationality != "indian" and (p.tier <= 2 or p.brand_value >= 0.6):
                count += 1
        return count

    @property
    def overseas_slots_remaining(self) -> int:
        return 4 - self.overseas_slots_used


# ---------------------------------------------------------
# AUCTION STATE & ACTIONS
# ---------------------------------------------------------

class BidAction(BaseModel):
    action_type: Literal["START", "BID", "PASS", "NEXT"]
    team_id: str
    amount: Optional[int] = None
    

class ActionResponse(BaseModel):
    status: Literal["OK", "ERROR"]
    error_msg: Optional[str] = None


class AuctionState(BaseModel):
    current_player: Optional[Player] = None
    current_bid: int = 0
    highest_bidder: Optional[str] = None
    
    # Track current active active bidders for the current player
    active_bidders: List[str] = Field(default_factory=list)
    bidding_rounds: int = 0
    
    # Master records of teams and sold players
    teams: Dict[str, Team] = Field(default_factory=dict)
    rtm_history: Dict[str, str] = Field(default_factory=dict)
    unsold_players: List[Player] = Field(default_factory=list)
    sold_players: List[Player] = Field(default_factory=list)
    truly_unsold_players: List[Player] = Field(default_factory=list)
    
    is_auction_complete: bool = False
    is_accelerated_phase: bool = False