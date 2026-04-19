import json
from typing import Dict, Any

class MemoryStore:
    def __init__(self, profiles_path: str = "data/team_profiles.json"):
        self.team_profiles = self._load_profiles(profiles_path)
        # Runtime memory
        self.rivalry_memory: Dict[str, Dict[str, int]] = {}  # E.g. {"MI": {"CSK": 5}}
        self.price_inflation_trends: Dict[str, float] = {}   # Track average role sale price
        self.role_scarcity_index: Dict[str, float] = {
            "batter": 1.0,
            "bowler": 1.0,
            "all_rounder": 1.0,
            "wicket_keeper": 1.0
        }
        self.price_drive_events: list[dict] = []
        self.desperation_events: list[dict] = []

    def _load_profiles(self, path: str) -> dict:
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load profiles at {path}: {e}")
            return {}

    def get_team_personality(self, team_id: str) -> Dict[str, float]:
        return self.team_profiles.get(team_id, {
            "aggression": 0.5,
            "price_tolerance": 0.5,
            "star_bias": 0.5,
            "youth_bias": 0.5,
            "risk_aversion": 0.5
        })

    def update_scarcity_index(self, remaining_players: list, total_players_initial: list):
        """
        Calculates: remaining_players_in_role / total_players_in_role
        Called by Orchestrator after each player is sold or auction starts
        """
        for role in self.role_scarcity_index.keys():
            remain = sum(1 for p in remaining_players if p.role == role)
            total = sum(1 for p in total_players_initial if p.role == role)
            if total > 0:
                self.role_scarcity_index[role] = remain / total
            else:
                self.role_scarcity_index[role] = 0.0

    def record_rivalry(self, active_bidders: list):
        """If two specific teams get into a long bidding war, increase rivalry score."""
        if len(active_bidders) == 2:
            t1, t2 = active_bidders
            if t1 not in self.rivalry_memory:
                self.rivalry_memory[t1] = {}
            if t2 not in self.rivalry_memory:
                self.rivalry_memory[t2] = {}
                
            self.rivalry_memory[t1][t2] = self.rivalry_memory[t1].get(t2, 0) + 1
            self.rivalry_memory[t2][t1] = self.rivalry_memory[t2].get(t1, 0) + 1
