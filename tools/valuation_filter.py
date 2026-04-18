
from typing import Dict
from engine.state import Player, Team


class ValuationFilter:
    def __init__(self, team: Team, player: Player,
                 personality: Dict[str, float], scarcity_index: float):
        self.team = team
        self.player = player
        self.personality = personality
        self.scarcity_index = scarcity_index


    @staticmethod
    def compute_scarcity_multiplier(role: str, state) -> float:
        remaining = [p for p in state.unsold_players if p.role == role]
        count = len(remaining)
        if count == 1:
            return 2.0
        elif count <= 3:
            return 1.7
        elif count <= 6:
            return 1.4
        return 1.0

    @staticmethod
    def compute_budget_reservation(state, team: Team) -> int:
        needed = max(0, 15 - team.squad_size)
        if needed == 0:
            return 0
            
        remaining_pool = state.unsold_players
        if not remaining_pool:
            return 0
            
        avg_cost = sum(p.base_price for p in remaining_pool) / len(remaining_pool)
        return int(needed * avg_cost)

    def compute_specialist_need(self, player: Player, team: Team) -> float:
        """Returns a multiplier 0.7-1.5 based on how many specialist_tags fill a gap."""
        if not player.specialist_tags:
            return 1.0
            
        if "bits-and-pieces" in player.specialist_tags:
            return 0.7  # Impact Player rule penalty
            
        # Priority mapping based on team personality
        priority_tags = set()
        if self.personality.get("pace_bias", 0.5) > 0.8:
            priority_tags.update(["pace-powerplay", "pace-death", "pace-middle", "swing"])
        if self.personality.get("spin_bias", 0.5) > 0.8:
            priority_tags.update(["wrist-spin", "finger-spin"])
        if self.personality.get("allrounder_bias", 0.5) > 0.8:
            priority_tags.update(["batting-allrounder", "bowling-allrounder"])
        if self.personality.get("aggression", 0.5) > 0.8:
            priority_tags.update(["finisher", "hard-hitting"])

        multipliers = []
        for tag in player.specialist_tags:
            # Check team roster for this tag
            # We need to scan team.players and team.retained_players
            all_team_players = team.players + team.retained_players
            tag_count = sum(1 for p in all_team_players if tag in p.specialist_tags)
            
            if tag_count >= 2:
                multipliers.append(0.8) # Redundancy penalty
            elif tag_count == 0:
                if tag in priority_tags:
                    multipliers.append(1.4) # Priority bonus
                else:
                    multipliers.append(1.2) # General gap bonus
            else:
                multipliers.append(1.0) # Neutral
                
        if not multipliers:
            return 1.0
        return max(0.7, min(1.5, sum(multipliers) / len(multipliers)))

    def compute_overseas_penalty(self, player: Player, team: Team) -> float:
        """Calculates penalty/bonus for overseas players based on current starters."""
        if player.nationality == "indian":
            return 1.0
            
        xi_count = team.overseas_xi_count()
        if xi_count >= 4:
            return 0.2  # Team already has 4 overseas starters
        elif xi_count == 3:
            return 0.85 # One more slot, slight caution
        elif xi_count < 3:
            return 1.1  # Team needs overseas quality
        return 1.0

    def calculate_max_price(self, state=None) -> int:
        # Post-retention calibrated tier bases
        # Tier 1 = franchise-defining (Pant, Shreyas, Starc)
        # Tier 2 = solid starters (Chahal, Curran, Jansen)
        # Tier 3 = squad depth, Tier 4 = filler/uncapped
        tier_base = {1: 35000000, 2: 7000000, 3: 2500000, 4: 1000000}
        base_val = tier_base.get(self.player.tier, 4000000)

        # Star and brand value boost
        if self.player.is_star:
            base_val += int(self.personality["star_bias"] * 22000000)
        base_val += int(self.player.brand_value * self.personality["star_bias"] * 14000000)

        # Recent form adjustment
        form_multiplier = 0.7 + (self.player.recent_form * 0.6)
        base_val = int(base_val * form_multiplier)

        # Youth and Hype bias
        if self.player.is_youth or self.player.age < 23:
            youth_base = int(self.personality["youth_bias"] * 12000000)
            if self.player.tier <= 2:
                hype_multiplier = 1.0 + (self.player.hype_score * self.personality.get("youth_bias", 0.3) * 1.8)
                youth_base = int(youth_base * hype_multiplier)
            base_val += youth_base

        # Veteran bias
        if self.player.age > 30:
            base_val += int(self.personality["veteran_bias"] * 8000000)

        # Specialist need multiplier
        specialist_mult = self.compute_specialist_need(self.player, self.team)
        base_val = int(base_val * specialist_mult)

        # Overseas penalty/bonus
        overseas_mult = self.compute_overseas_penalty(self.player, self.team)
        base_val = int(base_val * overseas_mult)

        # Pace and spin bias
        if self.player.pace_bowler:
            base_val += int(self.personality["pace_bias"] * 10000000)
        if self.player.spin_bowler:
            base_val += int(self.personality["spin_bias"] * 10000000)

        # Allrounder bias
        if self.player.role == "all_rounder":
            base_val += int(self.personality["allrounder_bias"] * 12000000)

        # Scarcity adjustment
        if self.scarcity_index < 0.4:
            base_val = int(base_val * (1 + self.personality["scarcity_sensitivity"] * 0.25))

        # Squad need adjustment
        squad_need = self._get_squad_need_score()
        if squad_need > 0.8:
            base_val = int(base_val * (1 + self.personality["role_urgency_weight"] * 0.4))

        # Aggression multiplier
        max_price = int(base_val * (1 + self.personality["aggression"] * 0.4))

        # Tier-based budget ceiling multiplier
        slots_needed = max(1, self.team.min_squad_size - self.team.squad_size)
        avg_slot_budget = self.team.remaining_budget / slots_needed
        tier_multiplier = {1: 3.2, 2: 1.8, 3: 1.2, 4: 0.8}
        multiplier = tier_multiplier.get(self.player.tier, 1.2)
        
        # Generational Player Premium — only for true superstars
        if self.player.brand_value >= 0.9:
            multiplier *= 1.6
        elif self.player.brand_value >= 0.8:
            multiplier *= 1.3
        elif self.player.is_star or self.player.brand_value >= 0.7:
            multiplier *= 1.15
            
        # Impact Player Rule Reality
        if self.player.role == "all_rounder" and not self.player.is_star and self.player.brand_value < 0.7:
            multiplier *= 0.4
            
        max_price = min(max_price, int(avg_slot_budget * multiplier * self.personality["price_tolerance"]))

        # Conservatism factor
        conservatism_factor = 1.0 - (self.personality["budget_conservatism"] * 0.15)
        
        if self.scarcity_index < 0.25:
            desperation = self.personality["scarcity_sensitivity"] * 0.3
            conservatism_factor = min(1.3, conservatism_factor + desperation)
            
        max_price = min(max_price, int(avg_slot_budget * multiplier * self.personality["price_tolerance"] * conservatism_factor))

        # HARD CAP based on remaining budget percentage
        if self.player.brand_value >= 0.9 and self.player.is_star:
            hard_cap = int(self.team.remaining_budget * 0.35)
        elif self.player.brand_value >= 0.8:
            hard_cap = int(self.team.remaining_budget * 0.22)
        else:
            hard_cap = int(self.team.remaining_budget * 0.12)
        max_price = min(max_price, hard_cap)

        import random
        jitter = random.uniform(0.95, 1.05)
        max_price = int(max_price * jitter)

        if self.team.squad_size < 15:
            max_price = max(max_price, self.player.base_price)

        return max_price

    def _get_squad_need_score(self) -> float:
        role_count = self.team.roles_count.get(self.player.role, 0)
        if role_count == 0:
            return 1.0
        if role_count >= 6:
            return 0.0
        return max(0.0, 1.0 - (role_count / 6.0))

    def get_budget_pressure(self) -> float:
        return self.team.remaining_budget / float(self.team.total_budget)

    def should_auto_pass(self, current_bid: int, max_price_override: int = None) -> bool:
        # Overseas slot check
        if self.player.nationality == "overseas":
            if self.team.overseas_slots_used >= 8: # IPL allows 8 in squad
                return True
                
        # Role limits
        role_limits = {"batter": 9, "bowler": 9, "all_rounder": 8, "wicket_keeper": 4}
        limit = role_limits.get(self.player.role, 6)
        if self.team.roles_count.get(self.player.role, 0) >= limit:
            if not self.player.is_star and self.player.brand_value < 0.85:
                return True

        if self.team.squad_size >= self.team.max_squad_size:
            return True

        from engine.auction_engine import get_next_bid
        next_bid = get_next_bid(current_bid)
        
        MIN_BASE_PRICE = 2000000
        slots_to_minimum = max(0, 15 - (self.team.squad_size + 1))
        required_reserve = slots_to_minimum * MIN_BASE_PRICE
        if next_bid > (self.team.remaining_budget - required_reserve):
            return True

        max_price = max_price_override if max_price_override is not None else self.calculate_max_price()
        
        if self.team.squad_size >= 6 and self.team.roles_count.get(self.player.role, 0) == 0:
            return False

        if current_bid > max_price:
            return True

        return False
