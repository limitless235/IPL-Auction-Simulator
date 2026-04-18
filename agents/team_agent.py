import random
from typing import Dict
from pydantic import BaseModel
from engine.state import Player, Team
from tools.valuation_filter import ValuationFilter


class AgentDecision(BaseModel):
    decision: str  # "BID" or "PASS"


# Target squad blueprints per team — how many of each role they want
# Based on real IPL squad building patterns
SQUAD_BLUEPRINTS = {
    "MI":   {"batter": 5, "bowler": 7, "all_rounder": 5, "wicket_keeper": 2},
    "CSK":  {"batter": 4, "bowler": 6, "all_rounder": 7, "wicket_keeper": 2},
    "RCB":  {"batter": 6, "bowler": 5, "all_rounder": 6, "wicket_keeper": 2},
    "KKR":  {"batter": 4, "bowler": 5, "all_rounder": 8, "wicket_keeper": 2},
    "DC":   {"batter": 5, "bowler": 7, "all_rounder": 6, "wicket_keeper": 2},
    "RR":   {"batter": 5, "bowler": 6, "all_rounder": 6, "wicket_keeper": 2},
    "SRH":  {"batter": 5, "bowler": 6, "all_rounder": 6, "wicket_keeper": 2},
    "PBKS": {"batter": 5, "bowler": 7, "all_rounder": 5, "wicket_keeper": 2},
    "GT":   {"batter": 4, "bowler": 6, "all_rounder": 7, "wicket_keeper": 2},
    "LSG":  {"batter": 4, "bowler": 7, "all_rounder": 6, "wicket_keeper": 2},
}

# Default blueprint for unknown teams
DEFAULT_BLUEPRINT = {"batter": 5, "bowler": 6, "all_rounder": 6, "wicket_keeper": 2}


class TeamAgent:
    def __init__(self, team: Team, personality: Dict[str, float]):
        self.team = team
        self.personality = personality
        self.blueprint = SQUAD_BLUEPRINTS.get(team.id, DEFAULT_BLUEPRINT)

    def get_role_gap(self, role: str) -> float:
        """
        Returns a 0.0 to 1.0 score indicating how urgently this role is needed.
        1.0 = need this role badly, 0.0 = already at or over target for this role.
        Negative gap (over target) returns 0.0 but triggers auto-pass in should_skip.
        """
        target = self.blueprint.get(role, 0)
        current = self.team.roles_count.get(role, 0)
        if target == 0:
            return 0.0
        gap = target - current
        if gap <= 0:
            return 0.0
        # Normalise: gap of target = 1.0, gap of 1 = 1/target
        return min(1.0, gap / target)

    def is_role_full(self, role: str) -> bool:
        """Returns True if team has already met or exceeded blueprint target for this role."""
        target = self.blueprint.get(role, 0)
        current = self.team.roles_count.get(role, 0)
        return current >= target

    def slots_remaining_for_budget(self) -> int:
        """How many more players does this team need to reach min_squad_size."""
        return max(1, self.team.min_squad_size - self.team.squad_size)

    def make_decision(self, player: Player, current_bid: int,
                      scarcity_index: float, auction_progress: float = 0.5,
                      active_bidders: list = None, rivalry_memory: dict = None) -> AgentDecision:
        from engine.auction_engine import get_next_bid

        next_bid = get_next_bid(current_bid)

        # Hard filters
        if next_bid > self.team.remaining_budget:
            return AgentDecision(decision="PASS")
        if self.team.squad_size >= self.team.max_squad_size:
            return AgentDecision(decision="PASS")
        if player.nationality == "overseas" and self.team.overseas_slots_used >= 4:
            return AgentDecision(decision="PASS")

        # Blueprint hard stop — if role is full, never bid
        if self.is_role_full(player.role):
            return AgentDecision(decision="PASS")

        # Valuation filter
        filter_tool = ValuationFilter(self.team, player, self.personality, scarcity_index)
        if filter_tool.should_auto_pass(current_bid):
            return AgentDecision(decision="PASS")

        # Base score
        score = 0.0

        # Role gap urgency — core of the blueprint system
        # Higher gap = stronger need = higher score boost
        role_gap = self.get_role_gap(player.role)
        score += role_gap * self.personality["role_urgency_weight"] * 1.2

        # Auction phase aggression
        if auction_progress < 0.33:
            score += self.personality["early_aggression"] * 0.35
        else:
            score += self.personality["aggression"] * 0.35

        # Late value hunting
        if auction_progress > 0.66 and player.tier >= 3:
            score += self.personality["late_value_hunting"] * 0.15

        # Star and brand value - huge bump for stars regardless of Tier
        if player.is_star:
            score += self.personality["star_bias"] * 0.35 + 0.25
        score += player.brand_value * self.personality["star_bias"] * 0.15

        # Tier scoring - reduced to stop marquee players dominating
        tier_score = {1: 0.15, 2: 0.10, 3: 0.05, 4: 0.0}
        score += tier_score.get(player.tier, 0.0)

        # Recent form
        score += (player.recent_form - 0.5) * 0.15

        # Youth and veteran bias
        if player.is_youth or player.age < 23:
            score += self.personality["youth_bias"] * 0.1
        if player.age > 30:
            score += self.personality["veteran_bias"] * 0.08

        # Bowling type bias
        if player.pace_bowler:
            score += self.personality["pace_bias"] * 0.12
        if player.spin_bowler:
            score += self.personality["spin_bias"] * 0.12

        # Allrounder bias & Impact Player Rule Reality
        if player.role == "all_rounder":
            if player.is_star or player.brand_value >= 0.75:
                # Premium all-rounders are still highly coveted
                score += self.personality["allrounder_bias"] * 0.1
            else:
                # Average all-rounders are severely devalued due to the Impact Player rule
                score -= 0.25
        elif player.role in ["batter", "bowler"]:
            # Slight buff to pure specialists as teams prefer 12 specialists over mediocre balanced XIs
            score += 0.08

        # Overseas bias - significantly loosened so top foreigners aren't ignored
        if player.nationality == "overseas":
            score += self.personality["foreign_bias"] * 0.18
            score += self.personality["value_foreign_bias"] * 0.18

        # Scarcity sensitivity
        if scarcity_index < 0.4:
            score += self.personality["scarcity_sensitivity"] * (1.0 - scarcity_index) * 0.15
        if scarcity_index < 0.25:
            # Extreme desperation
            score += self.personality["scarcity_sensitivity"] * 0.25

        # Rivalry pressure
        if active_bidders and rivalry_memory:
            my_rivalries = rivalry_memory.get(self.team.id, {})
            max_rivalry_val = max([my_rivalries.get(opp, 0) for opp in active_bidders if opp != self.team.id] + [0])
            if max_rivalry_val >= 3:
                # Long bidding war with a sworn rival sparks spite-bidding
                score += (min(max_rivalry_val, 15) / 15.0) * self.personality["aggression"] * 0.25

        # Budget pressure
        budget_ratio = self.team.remaining_budget / self.team.total_budget
        if budget_ratio < 0.3:
            score -= self.personality["risk_aversion"] * 0.25
        if budget_ratio < 0.15 and not player.is_star:
            score -= 0.35

        # Budget conservatism early
        if auction_progress < 0.33:
            score -= self.personality["budget_conservatism"] * 0.1

        # Squad depth bias — teams with high depth bias keep bidding late
        # teams with low depth bias (KKR style) become conservative once XI is set
        xi_filled = self.team.squad_size >= 11
        if xi_filled and self.personality["squad_depth_bias"] < 0.5:
            score -= 0.2

        # Mandatory minimum reached: be extremely picky about filling up to 25
        if self.team.squad_size >= self.team.min_squad_size and not player.is_star:
            score -= 0.4
            
        # Base quality check: don't automatically buy bad Tier 4/3 players just to fill seats
        if player.tier >= 3 and player.recent_form < 0.6 and not player.is_youth:
            score -= 0.3

        # Disruption tendency
        if 0.35 <= score < 0.50:
            if random.random() < self.personality["disruption_tendency"] * 0.3:
                score += 0.2

        # Jitter
        score += random.gauss(0, 0.07)

        if score >= 0.5:
            return AgentDecision(decision="BID")
        return AgentDecision(decision="PASS")
