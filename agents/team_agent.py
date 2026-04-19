import json
import os
import random
from typing import Dict, Optional
from pydantic import BaseModel
from engine.state import Player, Team
from tools.valuation_filter import ValuationFilter

# Load team hit lists (named-player targets from real auction data)
_HITLIST_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'team_hitlists.json')
try:
    with open(_HITLIST_PATH) as _f:
        TEAM_HITLISTS = json.load(_f)
except (FileNotFoundError, json.JSONDecodeError):
    TEAM_HITLISTS = {}


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

# Realism Upgrade: Scout-Driven Bias (Breakout Performers)
# Teams value these specific Tier 3/4 players much higher based on real 2024 form.
SCOUT_FAVORITES = {
    "MI":   ["Naman Dhir", "Nehal Wadhera", "Anukul Roy"],
    "CSK":  ["Kumar Kartikeya", "Arjun Tendulkar"],
    "RCB":  ["Rasikh Salam Dar", "Harshit Rana", "Prasidh Krishna"],
    "PBKS": ["Shashank Singh", "Ashutosh Sharma", "Nehal Wadhera"],
    "SRH":  ["Nitish Kumar Reddy", "Abdul Samad", "Abhishek Sharma"],
    "LSG":  ["Mayank Yadav", "Abdul Samad", "Ayush Badoni"],
    "KKR":  ["Harshit Rana", "Ramandeep Singh", "Angkrish Raghuvanshi"],
    "RR":   ["Vaibhav Suryavanshi", "Tanush Kotian"],
    "DC":   ["Abishek Porel", "Rasikh Salam Dar"],
    "GT":   ["Sai Kishore", "Shahrukh Khan"]
}


class TeamAgent:
    def __init__(self, team: Team, personality: Dict[str, float]):
        self.team = team
        self.personality = personality
        self.blueprint = SQUAD_BLUEPRINTS.get(team.id, DEFAULT_BLUEPRINT)
        
        # Named-player hit lists — apply ±35% jitter for significant cross-run variance
        hitlist_data = TEAM_HITLISTS.get(team.id, {})
        self.primary_targets = {}
        for t in hitlist_data.get("primary", []):
            jitter = random.uniform(0.65, 1.35)
            self.primary_targets[t["name"]] = int(t["max_lakhs"] * 100000 * jitter)
        self.fallback_targets = {}
        for t in hitlist_data.get("fallback", []):
            jitter = random.uniform(0.65, 1.35)
            self.fallback_targets[t["name"]] = int(t["max_lakhs"] * 100000 * jitter)
        
        # Compensatory escalation state
        self.lost_targets = []        # Names of primary targets lost to other teams
        self.compensatory_urgency = 0.0  # 0-1 scale, increases when losing targets

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

    def scan_upcoming_queue(self, role: str, state) -> dict:
        result = {"better_player_upcoming": False, "better_player_base_price": 0, "scarcity": 0}
        upcoming_role_players = [p for p in state.unsold_players if p.role == role]
        result["scarcity"] = len(upcoming_role_players)
        
        # Current player stats
        current_player = state.current_player
        
        for p in upcoming_role_players:
            # We consider a player "better" if they have a stronger tier or higher brand value
            if p.tier < current_player.tier or (p.tier == current_player.tier and p.brand_value > current_player.brand_value):
                result["better_player_upcoming"] = True
                result["better_player_base_price"] = p.base_price
                break
                
        return result

    def get_hitlist_info(self, player_name: str) -> dict:
        """Check if a player is on this team's hit list.
        Returns {"on_list": bool, "tier": "primary"/"fallback"/None, "max_price": int}
        """
        if player_name in self.primary_targets:
            return {"on_list": True, "tier": "primary", "max_price": self.primary_targets[player_name]}
        if player_name in self.fallback_targets:
            return {"on_list": True, "tier": "fallback", "max_price": self.fallback_targets[player_name]}
        return {"on_list": False, "tier": None, "max_price": 0}

    def record_lost_target(self, player_name: str, player_role: str):
        """Called when a primary target is won by another team.
        Triggers compensatory urgency for the next similar-role player."""
        if player_name in self.primary_targets:
            self.lost_targets.append({"name": player_name, "role": player_role})
            # Each lost primary target adds 0.15 urgency (caps at 0.5)
            self.compensatory_urgency = min(0.5, self.compensatory_urgency + 0.15)

    def compute_valuation(self, player: Player, state) -> float:
        # Base valuation from existing filter
        scarcity = 1.0
        filter_tool = ValuationFilter(self.team, player, self.personality, scarcity)
        
        # Calculate per-team hype noise
        import hashlib
        seed_str = f"{self.team.name}_{player.id}"
        seed = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % 1000000
        team_rng = random.Random(seed)
        team_specific_noise = team_rng.uniform(0, 0.1)
        
        # Temporarily inject noise into player for this team's calculation
        original_hype = player.hype_score
        player.hype_score = min(1.0, original_hype + team_specific_noise)
        
        # --- SCOUT BIAS ---
        scout_multiplier = 1.0
        if player.name in SCOUT_FAVORITES.get(self.team.id, []):
            # Breakout players get a massive boost (1.8x to 2.5x)
            scout_multiplier = 2.0
            if player.tier >= 4: scout_multiplier = 2.5 # Uncapped gems
            
        base_valuation = filter_tool.calculate_max_price(scout_multiplier=scout_multiplier)
        
        # Restore original hype score
        player.hype_score = original_hype

        # Per-evaluation random noise (±12%) — adds variance without crushing valuations
        eval_noise = random.uniform(0.88, 1.12)
        base_valuation = int(base_valuation * eval_noise)

        # --- HIT LIST SOFT INFLUENCE ---
        # Hit lists guide, not guarantee. Blend base valuation with ceiling.
        hit_info = self.get_hitlist_info(player.name)
        if hit_info["on_list"]:
            ceiling = hit_info["max_price"]
            if hit_info["tier"] == "primary":
                # Primary: 40% base + 60% ceiling — strong pull toward real auction price
                blended = int(base_valuation * 0.40 + ceiling * 0.60)
                base_valuation = max(base_valuation, blended)
            elif hit_info["tier"] == "fallback":
                # Fallback: 65% base + 35% ceiling — moderate preference
                blended = int(base_valuation * 0.65 + ceiling * 0.35)
                base_valuation = max(base_valuation, blended)

        # --- COMPENSATORY ESCALATION ---
        if self.compensatory_urgency > 0 and not hit_info["on_list"]:
            # If we lost targets, boost similar-role players
            lost_roles = [t["role"] for t in self.lost_targets]
            if player.role in lost_roles:
                escalation = 1.0 + self.compensatory_urgency
                base_valuation = int(base_valuation * escalation)

        # Apply Lookahead Enhancements
        scarcity_multiplier = ValuationFilter.compute_scarcity_multiplier(player.role, state)
        base_valuation = int(base_valuation * scarcity_multiplier)
        
        # Dynamic budget reservation — smarter than flat ₹20L per slot
        reserve = ValuationFilter.compute_dynamic_reservation(self.team, state)
        effective_budget = max(0, self.team.remaining_budget - reserve)
        base_valuation = min(base_valuation, effective_budget)
        
        # Patience discount — BUT not for hit list targets
        if not hit_info["on_list"]:
            queue_info = self.scan_upcoming_queue(player.role, state)
            if queue_info["better_player_upcoming"] and queue_info["better_player_base_price"] < self.team.remaining_budget * 0.35:
                base_valuation = int(base_valuation * 0.75)

        # --- DESPERATION MODE ---
        # Applied AFTER all other multipliers — overrides budget caution
        # when team is critically short on a mandatory role
        desperation = ValuationFilter.compute_desperation_multiplier(player, self.team, state)
        if desperation > 1.0:
            base_valuation = int(base_valuation * desperation)
            # Re-cap against absolute budget (can't bid more than you have)
            base_valuation = min(base_valuation, self.team.remaining_budget)

        # --- DEPTH PENALTY ---
        # If the squad is already mostly full (>= 20 players), be EXTREMELY picky
        # unless it's a star or a primary target. Prevents filler-bloat.
        if self.team.squad_size >= 20 and not player.is_star and not hit_info["on_list"]:
            base_valuation = int(base_valuation * 0.4)

        # --- FINAL JITTER & SANITY CHECKS ---
        jitter = random.gauss(1.0, 0.05)
        base_valuation = int(base_valuation * jitter)
        
        # Absolute Purse Ceiling: No single player is worth more than 30 Cr in this market.
        # This prevents the "KL Rahul 60Cr" outlier and ensures teams have budget for 18+ players.
        ABSOLUTE_CEILING = 300000000 # 30 Cr
        if base_valuation > ABSOLUTE_CEILING:
            base_valuation = ABSOLUTE_CEILING
            
        return base_valuation

    def should_invoke_rtm(self, player: Player, current_bid: int, state) -> bool:
        if self.team.rtm_cards <= 0:
            return False
            
        if state.rtm_history.get(player.name) != self.team.id:
            return False
            
        valuation = self.compute_valuation(player, state)
        if current_bid <= valuation * 1.1:
            reserve = ValuationFilter.compute_dynamic_reservation(self.team, state)
            if current_bid <= (self.team.remaining_budget - reserve):
                return True
        return False

    def compute_final_raise(self, player: Player, rtm_price: int, state) -> int:
        """2025 IPL Final Raise: after RTM is invoked, the buying team gets
        ONE chance to raise their bid by exactly one valid increment.

        Returns the raised amount, or None if this team passes (accepts the RTM).
        """
        from engine.auction_engine import get_next_bid_increment
        increment = get_next_bid_increment(rtm_price)
        final_raise_price = rtm_price + increment

        valuation = self.compute_valuation(player, state)
        # Only raise if: we value the player above the new price AND can afford it
        reserve = ValuationFilter.compute_dynamic_reservation(self.team, state)
        affordable = final_raise_price <= (self.team.remaining_budget - reserve)
        worth_it = valuation > final_raise_price

        if affordable and worth_it:
            return final_raise_price
        return None

    def should_match_final_raise(self, player: Player, final_raise_price: int, state) -> bool:
        """After the buying team raises, the RTM team decides whether to match
        the higher price or concede (keeping their RTM card).
        """
        valuation = self.compute_valuation(player, state)
        reserve = ValuationFilter.compute_dynamic_reservation(self.team, state)
        can_afford = final_raise_price <= (self.team.remaining_budget - reserve)
        worth_it = final_raise_price <= valuation * 1.1
        return can_afford and worth_it

    def should_price_drive(self, player: Player, current_bid: int, state) -> bool:
        if self.personality.get("aggression", 0.5) <= 0.6:
            return False
            
        if self.team.remaining_budget <= current_bid * 3:
            return False
            
        valuation = self.compute_valuation(player, state)
        if valuation >= current_bid:
            return False # We actually want them, so it's not a fake drive
            
        remaining_in_role = len([p for p in state.unsold_players if p.role == player.role])
        if remaining_in_role >= 3:
            return False # Not scarce enough to burn rivals over
            
        rivals = self.personality.get("rivalry_teams", [])
        for r_id in rivals:
            rival_team = state.teams.get(r_id)
            if rival_team and r_id in state.active_bidders:
                if rival_team.remaining_budget < current_bid * 2:
                    return True
        return False

    def compute_drive_bid(self, player: Player, current_bid: int, state) -> int:
        target_rival = None
        lowest_budget = float('inf')
        
        rivals = self.personality.get("rivalry_teams", [])
        for r_id in rivals:
            rival_team = state.teams.get(r_id)
            if rival_team and r_id in state.active_bidders:
                if rival_team.remaining_budget < lowest_budget:
                    lowest_budget = rival_team.remaining_budget
                    target_rival = rival_team
                    
        if not target_rival:
            return current_bid
            
        # Drive the price to exactly rival's max limit - 25L, rounded down
        from engine.auction_engine import get_next_bid
        
        target_price = target_rival.remaining_budget - 2500000
        max_own_risk = int(self.team.remaining_budget * 0.15)
        
        drive_limit = min(target_price, max_own_risk)
        
        # Absolute Market Ceiling for price driving
        ABSOLUTE_CEILING = 300000000
        if drive_limit > ABSOLUTE_CEILING:
            drive_limit = ABSOLUTE_CEILING
            
        # Find highest valid increment below drive_limit
        simulated_bid = current_bid
        while True:
            next_b = get_next_bid(simulated_bid)
            if next_b > drive_limit:
                break
            simulated_bid = next_b
            
        return simulated_bid

    def make_decision(self, player: Player, current_bid: int,
                      scarcity_index: float, auction_progress: float = 0.5,
                      active_bidders: list = None, rivalry_memory: dict = None, state=None) -> AgentDecision:
        from engine.auction_engine import get_next_bid

        next_bid = get_next_bid(current_bid)

        # Hard filters
        if next_bid > self.team.remaining_budget:
            return AgentDecision(decision="PASS")
        if self.team.squad_size >= self.team.max_squad_size:
            return AgentDecision(decision="PASS")
        # Overseas slot check — IPL allows 8 in squad
        if player.nationality == "overseas" and self.team.overseas_slots_used >= 8:
            return AgentDecision(decision="PASS")

        # Blueprint hard stop — if role is full, never bid (unless they are a massive superstar)
        if self.is_role_full(player.role):
            if not player.is_star and player.brand_value < 0.85:
                return AgentDecision(decision="PASS")

        # Valuation filter
        filter_tool = ValuationFilter(self.team, player, self.personality, scarcity_index)
        
        max_price_override = None
        if state is not None:
            max_price_override = self.compute_valuation(player, state)
            
        # Logging for scout favorites (internal simulation signal)
        if player.name in SCOUT_FAVORITES.get(self.team.id, []) and next_bid <= (max_price_override or 0):
            if current_bid == player.base_price:
                 print(f"🎯 [SCOUT FAVORITE] {self.team.id} is targeting breakout star {player.name}!")
            
        if filter_tool.should_auto_pass(current_bid, max_price_override=max_price_override):
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
            # Hype-driven interest — hyped youngsters attract more bidders,
            # creating the multi-team wars that drive surprise prices.
            # Effect is strongest for lower tiers where hype is the main signal.
            if player.hype_score > 0.3:
                hype_tier_boost = {1: 0.05, 2: 0.10, 3: 0.18, 4: 0.25}
                score += hype_tier_boost.get(player.tier, 0.12) * self.personality.get("youth_bias", 0.5)
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

    def submit_accelerated_shortlist(self, unsold_players: list, state) -> list:
        """Submit up to 5 player names from the unsold pool for the accelerated phase.
        
        Selection logic:
        1. Prioritize players that fill the team's biggest role gaps
        2. Among gap-fillers, prefer higher tier / brand value
        3. If no gaps remain, pick best-value cheap players to fill squad depth
        """
        if self.team.squad_size >= self.team.max_squad_size:
            return []  # Squad is full, no interest

        # Score each unsold player by how much we need them
        scored = []
        for player in unsold_players:
            # Hard filters — skip players we can't legally buy
            if player.nationality == "overseas" and self.team.overseas_slots_used >= 8:
                continue
                
            role_gap = self.get_role_gap(player.role)
            # Composite score: role gap urgency + quality
            quality = player.brand_value * 0.3 + (5 - player.tier) / 5 * 0.3 + player.recent_form * 0.2
            urgency = role_gap * self.personality.get("role_urgency_weight", 0.7)
            
            # --- REALISM: Personality-driven variety ---
            # Introduce a jitter based on team personality to avoid identical shortlists
            # Aggressive teams take more risks on low-tier hype, risk-averse teams stick to high-tier only
            variety_jitter = random.gauss(1.0, 0.15)
            if player.tier >= 3:
                variety_jitter *= (1.0 + self.personality.get("disruption_tendency", 0.5) * player.hype_score)
            
            total = (urgency + quality) * variety_jitter
            
            # Penalty for bits-and-pieces all-rounders
            if "bits-and-pieces" in player.specialist_tags:
                total *= 0.5
                
            scored.append((total, player.name))
        
        # Sort by score descending, take top 5
        scored.sort(key=lambda x: -x[0])
        return [name for _, name in scored[:5]]
