from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Float, Text
from sqlalchemy.orm import relationship
from database import Base


class Team(Base):
    """Team model for multi-sport teams (Cricket, Kabaddi, Volleyball)"""
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    sport = Column(String, default="cricket")  # cricket, kabaddi, volleyball
    captain = Column(String)
    phone = Column(String)
    email = Column(String)
    players = Column(Text, default="[]")  # JSON array: [{"name": "X", "is_captain": true}, ...]
    location = Column(String)
    experience = Column(String)
    
    # Stats
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    matches_played = Column(Integer, default=0)
    points = Column(Integer, default=0)
    
    # Simple aesthetic fields for the frontend
    logo_color_start = Column(String, default="#1e40af")
    logo_color_end = Column(String, default="#2563eb")
    symbol = Column(String, default="🏆")
    
    # Sport-specific stats
    # Cricket
    total_runs_scored = Column(Integer, default=0)
    total_wickets_taken = Column(Integer, default=0)
    
    # Kabaddi
    total_raid_points = Column(Integer, default=0)
    total_tackle_points = Column(Integer, default=0)
    
    # Volleyball
    total_sets_won = Column(Integer, default=0)


class Match(Base):
    """Match model for multi-sport matches with admin control"""
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    sport = Column(String, default="cricket")  # cricket, kabaddi, volleyball
    team1_id = Column(Integer, ForeignKey("teams.id"))
    team2_id = Column(Integer, ForeignKey("teams.id"))
    date = Column(String)  # Storing as string: "Feb 6, 2026"
    time = Column(String)
    venue = Column(String)
    status = Column(String, default="UPCOMING")  # UPCOMING, LIVE, COMPLETED
    result = Column(String, nullable=True)
    
    # Toss/Serve
    toss_winner_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    toss_choice = Column(String, nullable=True)  # bat/bowl for cricket, raid/defend for kabaddi
    
    # ============================================
    # CRICKET-SPECIFIC FIELDS
    # ============================================
    total_overs = Column(Integer, default=20)
    batting_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    bowling_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    
    # First innings
    total_runs = Column(Integer, default=0)
    wickets = Column(Integer, default=0)
    overs = Column(Float, default=0.0)
    
    # Second innings tracking
    current_innings = Column(Integer, default=1)  # 1 or 2
    target = Column(Integer, nullable=True)
    
    # Second innings scores
    innings2_runs = Column(Integer, default=0)
    innings2_wickets = Column(Integer, default=0)
    innings2_overs = Column(Float, default=0.0)
    
    # Ball-by-ball history as JSON
    ball_history = Column(Text, default="[]")  # JSON: [{"ball": 1, "runs": 4, "wicket": false, ...}]
    
    # ============================================
    # KABADDI-SPECIFIC FIELDS
    # ============================================
    half_duration_minutes = Column(Integer, default=20)
    current_half = Column(Integer, default=1)  # 1 or 2
    
    # Team 1 Kabaddi scores
    team1_raid_points = Column(Integer, default=0)
    team1_tackle_points = Column(Integer, default=0)
    team1_all_outs = Column(Integer, default=0)
    team1_bonus_points = Column(Integer, default=0)
    
    # Team 2 Kabaddi scores
    team2_raid_points = Column(Integer, default=0)
    team2_tackle_points = Column(Integer, default=0)
    team2_all_outs = Column(Integer, default=0)
    team2_bonus_points = Column(Integer, default=0)
    
    # ============================================
    # VOLLEYBALL-SPECIFIC FIELDS
    # ============================================
    ttp_points = Column(Integer, default=0)  # 0 = match mode (best of sets), >0 = TTP mode (first to X)
    total_sets = Column(Integer, default=3)  # Best of 3 or 5 in match mode
    current_set = Column(Integer, default=1)
    serve_team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    
    # Team 1 Volleyball scores
    team1_sets = Column(Integer, default=0)
    team1_current_points = Column(Integer, default=0)
    team1_set_points = Column(Text, default="[]")  # JSON: [25, 23, 15] (points per set)
    
    # Team 2 Volleyball scores
    team2_sets = Column(Integer, default=0)
    team2_current_points = Column(Integer, default=0)
    team2_set_points = Column(Text, default="[]")  # JSON: [20, 25, 10]
    
    # Point history for undo
    point_history = Column(Text, default="[]")  # JSON: [{"team": 1, "action": "point"}, ...]
    
    # ============================================
    # RELATIONSHIPS
    # ============================================
    team1 = relationship("Team", foreign_keys=[team1_id])
    team2 = relationship("Team", foreign_keys=[team2_id])
