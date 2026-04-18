
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
        tier_base = {1: 55000000, 2: 30000000, 3: 15000000, 4: 5000000}
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

        # Tier-based multiplier for marquee flexibility
        slots_needed = max(1, self.team.min_squad_size - self.team.squad_size)
        avg_slot_budget = self.team.remaining_budget / slots_needed
        tier_multiplier = {1: 4.5, 2: 3.0, 3: 1.8, 4: 1.2}
        multiplier = tier_multiplier.get(self.player.tier, 2.0)
        
        # Generational Player Premium - allows teams to momentarily shatter mathematical ceilings 
        # to bid historic, record-breaking amounts on iconic franchise-defining superstars.
        if self.player.brand_value >= 0.85:
            multiplier *= 1.8  # e.g., 4.5 -> 8.1
        elif self.player.is_star or self.player.brand_value >= 0.7:
            multiplier *= 1.4  # e.g., 4.5 -> 6.3
            
        # Impact Player Rule Reality
        if self.player.role == "all_rounder" and not self.player.is_star and self.player.brand_value < 0.7:
            # Drastically slash the budget multiplier for average all-rounders
            multiplier *= 0.4
            
        max_price = min(max_price, int(avg_slot_budget * multiplier * self.personality["price_tolerance"]))

        # Hard cap at price_tolerance * remaining_budget
        # Cap at 29% of remaining budget for any single player
        conservatism_factor = 1.0 - (self.personality["budget_conservatism"] * 0.15)
        
        # Ignore conservatism and push absolute limit if extremely desperate
        if self.scarcity_index < 0.25:
            desperation = self.personality["scarcity_sensitivity"] * 0.4
            conservatism_factor = min(1.5, conservatism_factor + desperation)
            
        max_price = min(max_price, int(avg_slot_budget * multiplier * self.personality["price_tolerance"] * conservatism_factor))

        import random
        # Add realistic minor variance (+/- 5%) to max bid ceilings, representing 
        # small boardroom disagreements during high-stakes bidding wars.
        jitter = random.uniform(0.95, 1.05)
        max_price = int(max_price * jitter)

        # Prevent false auto-pass on extremely empty squads that can afford base price
        if self.team.squad_size < 15:
            max_price = max(max_price, self.player.base_price)

        return max_price

    def _get_squad_need_score(self) -> float:
    # Simple check — does team have any of this role yet
        role_count = self.team.roles_count.get(self.player.role, 0)
        if role_count == 0:
            return 1.0
        if role_count >= 6:
            return 0.0
        return max(0.0, 1.0 - (role_count / 6.0))

    def get_budget_pressure(self) -> float:
        return self.team.remaining_budget / float(self.team.total_budget)

    def should_auto_pass(self, current_bid: int) -> bool:
        # Overseas slot check
        if self.player.nationality == "overseas":
            if self.team.overseas_slots_used >= 4:
                return True
        # Softened hard stop to allow teams to hoard steals while maintaining baseline balance
        role_limits = {"batter": 9, "bowler": 9, "all_rounder": 8, "wicket_keeper": 4}
        limit = role_limits.get(self.player.role, 6)
        if self.team.roles_count.get(self.player.role, 0) >= limit:
            return True

        # Squad full
        if self.team.squad_size >= self.team.max_squad_size:
            return True

        # No budget for next bid
        from engine.auction_engine import get_next_bid
        next_bid = get_next_bid(current_bid)
        
        # Mathematical Budget Reserve check to guarantee playing 15
        MIN_BASE_PRICE = 2000000
        slots_to_minimum = max(0, 15 - (self.team.squad_size + 1))
        required_reserve = slots_to_minimum * MIN_BASE_PRICE
        if next_bid > (self.team.remaining_budget - required_reserve):
            return True

        # Budget pressure scaling
        pressure = self.get_budget_pressure()
        risk_aversion = self.personality["risk_aversion"]
        if pressure < 0.4:
            risk_aversion = min(1.0, risk_aversion * 1.3)

        # Max price check
        max_price = self.calculate_max_price()
        
        # Critical role desperation
        if self.team.squad_size >= 6 and self.team.roles_count.get(self.player.role, 0) == 0:
            return False # Bypass max_price check, we desperately need this role!

        if current_bid > max_price:
            return True

        return False