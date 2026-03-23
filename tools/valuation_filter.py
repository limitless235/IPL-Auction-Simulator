
from typing import Dict
from engine.state import Player, Team


class ValuationFilter:
    def __init__(self, team: Team, player: Player,
                 personality: Dict[str, float], scarcity_index: float):
        self.team = team
        self.player = player
        self.personality = personality
        self.scarcity_index = scarcity_index

    def calculate_max_price(self) -> int:
        # Tier-based market valuation
        tier_base = {1: 80000000, 2: 40000000, 3: 15000000, 4: 5000000}
        base_val = tier_base.get(self.player.tier, 30000000)

        # Star and brand value boost
        if self.player.is_star:
            base_val += int(self.personality["star_bias"] * 40000000)
        base_val += int(self.player.brand_value * self.personality["star_bias"] * 20000000)

        # Recent form adjustment
        form_multiplier = 0.7 + (self.player.recent_form * 0.6)
        base_val = int(base_val * form_multiplier)

        # Youth bias
        if self.player.is_youth or self.player.age < 23:
            base_val += int(self.personality["youth_bias"] * 30000000)

        # Veteran bias
        if self.player.age > 30:
            base_val += int(self.personality["veteran_bias"] * 20000000)

        # Pace and spin bias
        if self.player.pace_bowler:
            base_val += int(self.personality["pace_bias"] * 20000000)
        if self.player.spin_bowler:
            base_val += int(self.personality["spin_bias"] * 20000000)

        # Allrounder bias
        if self.player.role == "all_rounder":
            base_val += int(self.personality["allrounder_bias"] * 25000000)

        # Overseas value bias
        if self.player.nationality == "overseas":
            base_val += int(self.personality["value_foreign_bias"] * 20000000)
            base_val += int(self.personality["foreign_bias"] * 15000000)

        # Scarcity adjustment
        if self.scarcity_index < 0.4:
            base_val = int(base_val * (1 + self.personality["scarcity_sensitivity"] * 0.3))

        # Squad need adjustment
        squad_need = self._get_squad_need_score()
        if squad_need > 0.8:
            base_val = int(base_val * (1 + self.personality["role_urgency_weight"] * 0.5))

        # Aggression multiplier
        max_price = int(base_val * (1 + self.personality["aggression"] * 0.5))

        # Hard cap at price_tolerance * remaining_budget
        # Cap at 30% of total budget for any single player
        max_price = min(max_price, int(self.team.total_budget * 0.28 * self.personality["price_tolerance"]))

        return max_price

    def _get_squad_need_score(self) -> float:
        role_count = self.team.roles_count.get(self.player.role, 0)
        if role_count == 0:
            return 1.0
        if role_count >= 5:
            return 0.0
        return max(0.0, 1.0 - (role_count / 5.0))

    def get_budget_pressure(self) -> float:
        return self.team.remaining_budget / float(self.team.total_budget)

    def should_auto_pass(self, current_bid: int) -> bool:
        # Overseas slot check
        if self.player.nationality == "overseas":
            if self.team.overseas_slots_used >= 4:
                return True

        # Squad full
        if self.team.squad_size >= self.team.max_squad_size:
            return True

        # No budget for next bid
        from engine.auction_engine import get_next_bid
        next_bid = get_next_bid(current_bid)
        if next_bid > self.team.remaining_budget:
            return True

        # Budget pressure scaling
        pressure = self.get_budget_pressure()
        risk_aversion = self.personality["risk_aversion"]
        if pressure < 0.4:
            risk_aversion = min(1.0, risk_aversion * 1.3)
        if pressure < 0.2:
            if self._get_squad_need_score() < 0.8:
                return True

        # Max price check
        max_price = self.calculate_max_price()
        if current_bid > max_price:
            return True

        return False