# Rank tier thresholds — single source of truth
# To rebalance, only change this list
#rank.py
RANK_TIERS = [
    (0,    "Bronze Explorer"),
    (500,  "Silver Navigator"),
    (1500, "Gold Cartographer"),
    (3000, "World Master"),
]

# XP awarded per match outcome
XP_WIN  = 100
XP_LOSS = 20
XP_DRAW = 50

# Rank points per match outcome
RP_WIN  = 25
RP_LOSS = -15


def calculate_rank_tier(rank_points: int) -> str:
    """Return the tier name for a given rank_points value."""
    tier = RANK_TIERS[0][1]
    for threshold, name in RANK_TIERS:
        if rank_points >= threshold:
            tier = name
    return tier


def calculate_xp_gain(won: bool, correct: int, streak: int) -> int:
    """
    XP = base win/loss amount
       + 5 per correct answer
       + streak bonus (10 per streak level above 2)
    """
    base = XP_WIN if won else XP_LOSS
    answer_bonus = correct * 5
    streak_bonus = max(0, streak - 2) * 10
    return base + answer_bonus + streak_bonus


def calculate_rank_points_delta(won: bool, opponent_rank_points: int, own_rank_points: int) -> int:
    """
    Simple ELO-inspired delta:
    - Beating a higher-ranked opponent gives more RP
    - Losing to a lower-ranked opponent costs more RP
    """
    diff = opponent_rank_points - own_rank_points
    if won:
        bonus = max(0, diff // 100)
        return RP_WIN + bonus
    else:
        penalty = max(0, -diff // 100)
        return RP_LOSS - penalty

