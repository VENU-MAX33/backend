from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import json

import models
from database import engine, SessionLocal

# Authentication removed - no login required

# Create Database Tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sports Arena API", description="Multi-sport live scoring platform for Cricket, Kabaddi, and Volleyball")

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =============================================================================
# PYDANTIC MODELS FOR REQUEST/RESPONSE
# =============================================================================

class PlayerInfo(BaseModel):
    name: str
    is_captain: bool = False


class TeamCreate(BaseModel):
    name: str
    sport: str = "cricket"  # cricket, kabaddi, volleyball
    captain: str
    phone: str
    email: str
    players: List[PlayerInfo]
    location: str
    experience: str


class TeamResponse(BaseModel):
    id: int
    name: str
    sport: str
    captain: str
    phone: str
    email: str
    players: str  # JSON string
    location: str
    experience: str
    wins: int
    losses: int
    matches_played: int
    points: int
    logo_color_start: str
    logo_color_end: str
    symbol: str

    class Config:
        from_attributes = True


class MatchCreate(BaseModel):
    team1_id: int
    team2_id: int
    date: str
    time: str
    venue: str
    sport: str = "cricket"
    # Sport-specific config
    total_overs: Optional[int] = 20          # Cricket
    half_duration: Optional[int] = 20        # Kabaddi (minutes per half)
    ttp_points: Optional[int] = 0            # Volleyball (0 = match mode, else TTP)
    total_sets: Optional[int] = 3            # Volleyball match mode


class MatchListResponse(BaseModel):
    id: int
    sport: str
    team1_name: str
    team2_name: str
    date: str
    time: str
    venue: str
    status: str
    result: Optional[str] = None
    # Quick score summary
    score_summary: Optional[str] = None

    class Config:
        from_attributes = True


class TossUpdate(BaseModel):
    winner_team_id: int
    choice: str  # bat/bowl (cricket), raid/defend (kabaddi), serve (volleyball)


class CricketScoreUpdate(BaseModel):
    run: int
    is_wicket: bool = False
    extra_type: Optional[str] = None  # "WD", "NB", "B", "LB"
    batsman_out: Optional[str] = None
    new_batsman: Optional[str] = None


class KabaddiScoreUpdate(BaseModel):
    team_id: int  # which team scored
    action: str   # "raid", "tackle", "super_tackle", "bonus", "self_out", "all_out"
    points: int = 1


class VolleyballScoreUpdate(BaseModel):
    team_id: int  # which team scored
    action: str   # "point", "undo", "set_won", "toggle_serve"


# =============================================================================
# WEBSOCKET MANAGER
# =============================================================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, match_id: int):
        await websocket.accept()
        if match_id not in self.active_connections:
            self.active_connections[match_id] = []
        self.active_connections[match_id].append(websocket)

    def disconnect(self, websocket: WebSocket, match_id: int):
        if match_id in self.active_connections:
            if websocket in self.active_connections[match_id]:
                self.active_connections[match_id].remove(websocket)
            if not self.active_connections[match_id]:
                del self.active_connections[match_id]

    async def broadcast(self, message: dict, match_id: int):
        if match_id in self.active_connections:
            for connection in self.active_connections[match_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    print(f"Error sending message: {e}")


manager = ConnectionManager()


# Authentication endpoints removed - no login required


# =============================================================================
# TEAM ENDPOINTS
# =============================================================================

def get_sport_symbol(sport: str) -> str:
    """Get default symbol for sport"""
    symbols = {"cricket": "🏏", "kabaddi": "🤼", "volleyball": "🏐"}
    return symbols.get(sport, "🏆")


def get_sport_colors(sport: str) -> tuple:
    """Get default colors for sport"""
    colors = {
        "cricket": ("#16a34a", "#22c55e"),
        "kabaddi": ("#ea580c", "#f97316"),
        "volleyball": ("#2563eb", "#3b82f6")
    }
    return colors.get(sport, ("#1e40af", "#2563eb"))


@app.post("/api/register", response_model=dict)
@app.post("/api/teams", response_model=dict)
def register_team(team: TeamCreate, db: Session = Depends(get_db)):
    """Register a new team (public endpoint)"""
    existing = db.query(models.Team).filter(models.Team.name == team.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Team name already taken")
    
    # Validate sport
    if team.sport not in ["cricket", "kabaddi", "volleyball"]:
        raise HTTPException(status_code=400, detail="Invalid sport. Must be cricket, kabaddi, or volleyball")
    
    # Validate minimum players
    min_players = {"cricket": 11, "kabaddi": 7, "volleyball": 6}
    if len(team.players) < min_players.get(team.sport, 6):
        raise HTTPException(
            status_code=400, 
            detail=f"{team.sport.title()} requires at least {min_players[team.sport]} players"
        )
    
    # Convert players list to JSON
    players_json = json.dumps([p.dict() for p in team.players])
    
    # Get sport-specific aesthetics
    color_start, color_end = get_sport_colors(team.sport)
    symbol = get_sport_symbol(team.sport)
    
    db_team = models.Team(
        name=team.name,
        sport=team.sport,
        captain=team.captain,
        phone=team.phone,
        email=team.email,
        players=players_json,
        location=team.location,
        experience=team.experience,
        logo_color_start=color_start,
        logo_color_end=color_end,
        symbol=symbol
    )
    db.add(db_team)
    db.commit()
    db.refresh(db_team)
    return {"id": db_team.id, "message": f"{team.sport.title()} team registered successfully"}


@app.get("/api/teams", response_model=List[TeamResponse])
def get_teams(sport: Optional[str] = None, db: Session = Depends(get_db)):
    """Get all teams, optionally filtered by sport"""
    query = db.query(models.Team)
    if sport:
        query = query.filter(models.Team.sport == sport)
    return query.all()


@app.get("/api/teams/{team_id}", response_model=TeamResponse)
def get_team(team_id: int, db: Session = Depends(get_db)):
    """Get a specific team by ID"""
    team = db.query(models.Team).filter(models.Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


# =============================================================================
# MATCH ENDPOINTS
# =============================================================================

@app.get("/api/matches", response_model=List[MatchListResponse])
def get_matches(
    sport: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get all matches, optionally filtered by sport and status"""
    query = db.query(models.Match)
    if sport:
        query = query.filter(models.Match.sport == sport)
    if status:
        query = query.filter(models.Match.status == status)
    
    matches = query.all()
    result = []
    for match in matches:
        t1 = db.query(models.Team).filter(models.Team.id == match.team1_id).first()
        t2 = db.query(models.Team).filter(models.Team.id == match.team2_id).first()
        
        # Generate score summary based on sport
        score_summary = None
        if match.sport == "cricket":
            if match.current_innings == 1:
                score_summary = f"{match.total_runs}/{match.wickets} ({match.overs} ov)"
            else:
                score_summary = f"{match.innings2_runs}/{match.innings2_wickets} ({match.innings2_overs} ov)"
        elif match.sport == "kabaddi":
            t1_total = match.team1_raid_points + match.team1_tackle_points + (match.team1_all_outs * 2) + match.team1_bonus_points
            t2_total = match.team2_raid_points + match.team2_tackle_points + (match.team2_all_outs * 2) + match.team2_bonus_points
            score_summary = f"{t1_total} - {t2_total}"
        elif match.sport == "volleyball":
            if match.ttp_points > 0:
                score_summary = f"{match.team1_current_points} - {match.team2_current_points}"
            else:
                score_summary = f"{match.team1_sets} - {match.team2_sets} sets"
        
        result.append({
            "id": match.id,
            "sport": match.sport,
            "team1_name": t1.name if t1 else "TBA",
            "team2_name": t2.name if t2 else "TBA",
            "date": match.date,
            "time": match.time,
            "venue": match.venue,
            "status": match.status,
            "result": match.result,
            "score_summary": score_summary
        })
    return result


@app.post("/api/matches", response_model=dict)
def create_match(
    match: MatchCreate,
    db: Session = Depends(get_db)
):
    """Create a new match (public endpoint for admin panel)"""
    team1 = db.query(models.Team).filter(models.Team.id == match.team1_id).first()
    team2 = db.query(models.Team).filter(models.Team.id == match.team2_id).first()
    
    if not team1 or not team2:
        raise HTTPException(status_code=404, detail="One or both teams not found")
    
    if match.team1_id == match.team2_id:
        raise HTTPException(status_code=400, detail="Teams must be different")
    
    # Validate teams are of correct sport
    if team1.sport != match.sport or team2.sport != match.sport:
        raise HTTPException(
            status_code=400, 
            detail=f"Both teams must be {match.sport} teams"
        )
    
    db_match = models.Match(
        sport=match.sport,
        team1_id=match.team1_id,
        team2_id=match.team2_id,
        date=match.date,
        time=match.time,
        venue=match.venue,
        status="UPCOMING",
        # created_by_id removed - match can be created without authentication
        # Cricket
        total_overs=match.total_overs or 20,
        batting_team_id=match.team1_id,
        bowling_team_id=match.team2_id,
        # Kabaddi
        half_duration_minutes=match.half_duration or 20,
        # Volleyball
        ttp_points=match.ttp_points or 0,
        total_sets=match.total_sets or 3,
        serve_team_id=match.team1_id
    )
    db.add(db_match)
    db.commit()
    db.refresh(db_match)
    
    return {
        "id": db_match.id,
        "message": f"{match.sport.title()} match created successfully.",
        "team1": team1.name,
        "team2": team2.name
    }


@app.get("/api/matches/{match_id}")
def get_match_details(
    match_id: int,
    db: Session = Depends(get_db)
):
    """Get detailed match information based on sport"""
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    t1 = db.query(models.Team).filter(models.Team.id == match.team1_id).first()
    t2 = db.query(models.Team).filter(models.Team.id == match.team2_id).first()
    is_admin = True  # All users have admin access now
    
    # Base response
    response = {
        "id": match.id,
        "sport": match.sport,
        "team1": {
            "id": t1.id if t1 else None,
            "name": t1.name if t1 else "TBA",
            "players": json.loads(t1.players) if t1 else [],
            "symbol": t1.symbol if t1 else "🏆",
            "color_start": t1.logo_color_start if t1 else "#1e40af",
            "color_end": t1.logo_color_end if t1 else "#2563eb"
        },
        "team2": {
            "id": t2.id if t2 else None,
            "name": t2.name if t2 else "TBA",
            "players": json.loads(t2.players) if t2 else [],
            "symbol": t2.symbol if t2 else "🏆",
            "color_start": t2.logo_color_start if t2 else "#1e40af",
            "color_end": t2.logo_color_end if t2 else "#2563eb"
        },
        "date": match.date,
        "time": match.time,
        "venue": match.venue,
        "status": match.status,
        "result": match.result,
        "is_admin": is_admin,
        "toss_winner_id": match.toss_winner_id,
        "toss_choice": match.toss_choice
    }
    
    # Add sport-specific data
    if match.sport == "cricket":
        batting = db.query(models.Team).filter(models.Team.id == match.batting_team_id).first()
        bowling = db.query(models.Team).filter(models.Team.id == match.bowling_team_id).first()
        
        response.update({
            "total_overs": match.total_overs,
            "current_innings": match.current_innings,
            "target": match.target,
            "batting_team": batting.name if batting else "TBA",
            "bowling_team": bowling.name if bowling else "TBA",
            "innings1": {
                "runs": match.total_runs,
                "wickets": match.wickets,
                "overs": match.overs
            },
            "innings2": {
                "runs": match.innings2_runs,
                "wickets": match.innings2_wickets,
                "overs": match.innings2_overs
            } if match.current_innings == 2 else None,
            "ball_history": json.loads(match.ball_history) if match.ball_history else []
        })
    
    elif match.sport == "kabaddi":
        response.update({
            "half_duration_minutes": match.half_duration_minutes,
            "current_half": match.current_half,
            "team1_score": {
                "raid_points": match.team1_raid_points,
                "tackle_points": match.team1_tackle_points,
                "all_outs": match.team1_all_outs,
                "bonus_points": match.team1_bonus_points,
                "total": match.team1_raid_points + match.team1_tackle_points + (match.team1_all_outs * 2) + match.team1_bonus_points
            },
            "team2_score": {
                "raid_points": match.team2_raid_points,
                "tackle_points": match.team2_tackle_points,
                "all_outs": match.team2_all_outs,
                "bonus_points": match.team2_bonus_points,
                "total": match.team2_raid_points + match.team2_tackle_points + (match.team2_all_outs * 2) + match.team2_bonus_points
            }
        })
    
    elif match.sport == "volleyball":
        response.update({
            "ttp_points": match.ttp_points,
            "total_sets": match.total_sets,
            "current_set": match.current_set,
            "serve_team_id": match.serve_team_id,
            "team1_score": {
                "sets": match.team1_sets,
                "current_points": match.team1_current_points,
                "set_points": json.loads(match.team1_set_points) if match.team1_set_points else []
            },
            "team2_score": {
                "sets": match.team2_sets,
                "current_points": match.team2_current_points,
                "set_points": json.loads(match.team2_set_points) if match.team2_set_points else []
            },
            "point_history": json.loads(match.point_history) if match.point_history else []
        })
    
    return response


@app.post("/api/matches/{match_id}/start")
def start_match(
    match_id: int,
    db: Session = Depends(get_db)
):
    """Start a match (public endpoint for admin panel)"""
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    match.status = "LIVE"
    db.commit()
    
    return {"message": "Match started", "status": "LIVE"}


@app.put("/api/matches/{match_id}/toss")
async def save_toss(
    match_id: int,
    toss: TossUpdate,
    db: Session = Depends(get_db)
):
    """Save toss result and set batting/serving team (public endpoint for admin panel)"""
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    # Validate winner team
    if toss.winner_team_id not in [match.team1_id, match.team2_id]:
        raise HTTPException(status_code=400, detail="Invalid toss winner team")
    
    match.toss_winner_id = toss.winner_team_id
    match.toss_choice = toss.choice
    
    # Set batting/bowling or serve based on choice
    other_team = match.team2_id if toss.winner_team_id == match.team1_id else match.team1_id
    
    if match.sport == "cricket":
        if toss.choice == "bat":
            match.batting_team_id = toss.winner_team_id
            match.bowling_team_id = other_team
        else:  # bowl
            match.batting_team_id = other_team
            match.bowling_team_id = toss.winner_team_id
    elif match.sport == "kabaddi":
        if toss.choice == "raid":
            match.batting_team_id = toss.winner_team_id  # Reusing as raiding team
        else:  # defend
            match.batting_team_id = other_team
    elif match.sport == "volleyball":
        match.serve_team_id = toss.winner_team_id
    
    db.commit()
    
    # Broadcast toss result
    t1 = db.query(models.Team).filter(models.Team.id == match.team1_id).first()
    t2 = db.query(models.Team).filter(models.Team.id == match.team2_id).first()
    winner = db.query(models.Team).filter(models.Team.id == toss.winner_team_id).first()
    
    await manager.broadcast({
        "event": "toss",
        "match_id": match_id,
        "winner": winner.name if winner else "TBA",
        "choice": toss.choice,
        "message": f"{winner.name if winner else 'Team'} won the toss and chose to {toss.choice}"
    }, match_id)
    
    return {"message": "Toss saved", "winner": winner.name if winner else "TBA", "choice": toss.choice}


# =============================================================================
# CRICKET SCORING
# =============================================================================

@app.post("/api/matches/{match_id}/score")
@app.put("/api/matches/{match_id}/score")
async def update_cricket_score(
    match_id: int,
    update: CricketScoreUpdate,
    db: Session = Depends(get_db)
):
    """Update cricket match score (public endpoint for admin panel)"""
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if match.sport != "cricket":
        raise HTTPException(status_code=400, detail="This endpoint is for cricket matches only")
    
    if match.status != "LIVE":
        raise HTTPException(status_code=400, detail="Match is not live")
    
    # Determine which innings
    if match.current_innings == 1:
        runs_attr, wickets_attr, overs_attr = 'total_runs', 'wickets', 'overs'
    else:
        runs_attr, wickets_attr, overs_attr = 'innings2_runs', 'innings2_wickets', 'innings2_overs'
    
    current_runs = getattr(match, runs_attr)
    current_wickets = getattr(match, wickets_attr)
    current_overs = getattr(match, overs_attr)
    
    # Ball entry for history
    ball_entry = {
        "ball": int(current_overs * 6) + int((current_overs % 1) * 10) + 1,
        "runs": update.run,
        "wicket": update.is_wicket,
        "extra_type": update.extra_type,
        "innings": match.current_innings
    }
    
    # Cricket scoring logic
    if update.extra_type in ["WD", "NB"]:  # Wide or No Ball
        setattr(match, runs_attr, current_runs + 1 + update.run)
        ball_entry["total_runs"] = 1 + update.run
    else:  # Normal delivery
        setattr(match, runs_attr, current_runs + update.run)
        ball_entry["total_runs"] = update.run
        # Increment balls
        balls = int(round((current_overs - int(current_overs)) * 10))
        balls += 1
        if balls == 6:
            setattr(match, overs_attr, int(current_overs) + 1.0)
        else:
            setattr(match, overs_attr, float(f"{int(current_overs)}.{balls}"))
    
    if update.is_wicket:
        setattr(match, wickets_attr, current_wickets + 1)
        ball_entry["batsman_out"] = update.batsman_out
        ball_entry["new_batsman"] = update.new_batsman
    
    # Save ball history
    history = json.loads(match.ball_history) if match.ball_history else []
    history.append(ball_entry)
    match.ball_history = json.dumps(history)
    
    db.commit()
    
    # Get updated values
    updated_runs = getattr(match, runs_attr)
    updated_wickets = getattr(match, wickets_attr)
    updated_overs = getattr(match, overs_attr)
    
    # Broadcast update
    batting = db.query(models.Team).filter(models.Team.id == match.batting_team_id).first()
    bowling = db.query(models.Team).filter(models.Team.id == match.bowling_team_id).first()
    
    await manager.broadcast({
        "event": "score_update",
        "sport": "cricket",
        "match_id": match_id,
        "score": updated_runs,
        "wickets": updated_wickets,
        "overs": updated_overs,
        "current_innings": match.current_innings,
        "target": match.target,
        "batting_team": batting.name if batting else "TBA",
        "bowling_team": bowling.name if bowling else "TBA",
        "status": match.status,
        "last_ball": ball_entry
    }, match_id)

    return {
        "message": "Score updated",
        "score": f"{updated_runs}/{updated_wickets}",
        "overs": updated_overs
    }


@app.post("/api/matches/{match_id}/end_innings")
async def end_innings(
    match_id: int,
    db: Session = Depends(get_db)
):
    """End current innings and switch to second innings (cricket) (public endpoint for admin panel)"""
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if match.sport != "cricket":
        raise HTTPException(status_code=400, detail="This endpoint is for cricket matches only")
    
    if match.current_innings == 2:
        raise HTTPException(status_code=400, detail="Second innings already in progress or match finished")
    
    # Set target and switch innings
    match.target = match.total_runs + 1
    match.current_innings = 2
    
    # Swap batting/bowling teams
    match.batting_team_id, match.bowling_team_id = match.bowling_team_id, match.batting_team_id
    
    db.commit()
    
    # Broadcast innings change
    t1 = db.query(models.Team).filter(models.Team.id == match.batting_team_id).first()
    t2 = db.query(models.Team).filter(models.Team.id == match.bowling_team_id).first()
    
    await manager.broadcast({
        "event": "innings_change",
        "match_id": match_id,
        "current_innings": 2,
        "target": match.target,
        "batting_team": t1.name if t1 else "TBA",
        "bowling_team": t2.name if t2 else "TBA",
        "message": f"Second innings started. Target: {match.target}"
    }, match_id)
    
    return {
        "message": "Second innings started",
        "target": match.target,
        "batting_team": t1.name if t1 else "TBA"
    }


# =============================================================================
# KABADDI SCORING
# =============================================================================

@app.post("/api/matches/{match_id}/kabaddi/score")
@app.put("/api/matches/{match_id}/kabaddi/score")
async def update_kabaddi_score(
    match_id: int,
    update: KabaddiScoreUpdate,
    db: Session = Depends(get_db)
):
    """Update kabaddi match score (public endpoint for admin panel)"""
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if match.sport != "kabaddi":
        raise HTTPException(status_code=400, detail="This endpoint is for kabaddi matches only")
    
    if match.status != "LIVE":
        raise HTTPException(status_code=400, detail="Match is not live")
    
    # Validate team
    if update.team_id not in [match.team1_id, match.team2_id]:
        raise HTTPException(status_code=400, detail="Invalid team ID")
    
    is_team1 = update.team_id == match.team1_id
    other_team = match.team2_id if is_team1 else match.team1_id
    
    # Apply score based on action
    if update.action == "raid":
        if is_team1:
            match.team1_raid_points += update.points
        else:
            match.team2_raid_points += update.points
    
    elif update.action == "tackle":
        if is_team1:
            match.team1_tackle_points += 1
        else:
            match.team2_tackle_points += 1
    
    elif update.action == "super_tackle":
        if is_team1:
            match.team1_tackle_points += 2
        else:
            match.team2_tackle_points += 2
    
    elif update.action == "bonus":
        if is_team1:
            match.team1_bonus_points += 1
        else:
            match.team2_bonus_points += 1
    
    elif update.action == "self_out":
        # Points go to opponent
        if is_team1:
            match.team2_raid_points += 1
        else:
            match.team1_raid_points += 1
    
    elif update.action == "all_out":
        if is_team1:
            match.team1_all_outs += 1
        else:
            match.team2_all_outs += 1
    
    db.commit()
    
    # Calculate totals
    team1_total = match.team1_raid_points + match.team1_tackle_points + (match.team1_all_outs * 2) + match.team1_bonus_points
    team2_total = match.team2_raid_points + match.team2_tackle_points + (match.team2_all_outs * 2) + match.team2_bonus_points
    
    # Broadcast update
    t1 = db.query(models.Team).filter(models.Team.id == match.team1_id).first()
    t2 = db.query(models.Team).filter(models.Team.id == match.team2_id).first()
    
    await manager.broadcast({
        "event": "score_update",
        "sport": "kabaddi",
        "match_id": match_id,
        "team1_score": {
            "name": t1.name if t1 else "Team 1",
            "raid_points": match.team1_raid_points,
            "tackle_points": match.team1_tackle_points,
            "all_outs": match.team1_all_outs,
            "bonus_points": match.team1_bonus_points,
            "total": team1_total
        },
        "team2_score": {
            "name": t2.name if t2 else "Team 2",
            "raid_points": match.team2_raid_points,
            "tackle_points": match.team2_tackle_points,
            "all_outs": match.team2_all_outs,
            "bonus_points": match.team2_bonus_points,
            "total": team2_total
        },
        "action": update.action,
        "scoring_team": t1.name if is_team1 else t2.name
    }, match_id)

    return {
        "message": "Score updated",
        "team1_total": team1_total,
        "team2_total": team2_total
    }


@app.post("/api/matches/{match_id}/kabaddi/half")
async def switch_kabaddi_half(
    match_id: int,
    db: Session = Depends(get_db)
):
    """Switch to second half in kabaddi (public endpoint for admin panel)"""
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if match.sport != "kabaddi":
        raise HTTPException(status_code=400, detail="This endpoint is for kabaddi matches only")
    
    match.current_half = 2
    db.commit()
    
    await manager.broadcast({
        "event": "half_change",
        "match_id": match_id,
        "current_half": 2,
        "message": "Second half started"
    }, match_id)
    
    return {"message": "Second half started"}


# =============================================================================
# VOLLEYBALL SCORING
# =============================================================================

@app.post("/api/matches/{match_id}/volleyball/score")
@app.put("/api/matches/{match_id}/volleyball/score")
async def update_volleyball_score(
    match_id: int,
    update: VolleyballScoreUpdate,
    db: Session = Depends(get_db)
):
    """Update volleyball match score (public endpoint for admin panel)"""
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    if match.sport != "volleyball":
        raise HTTPException(status_code=400, detail="This endpoint is for volleyball matches only")
    
    if match.status != "LIVE":
        raise HTTPException(status_code=400, detail="Match is not live")
    
    is_team1 = update.team_id == match.team1_id
    
    # Point history for undo
    history = json.loads(match.point_history) if match.point_history else []
    
    if update.action == "point":
        if is_team1:
            match.team1_current_points += 1
        else:
            match.team2_current_points += 1
        
        history.append({"team": 1 if is_team1 else 2, "action": "point"})
        match.point_history = json.dumps(history)
    
    elif update.action == "undo":
        if history:
            last = history.pop()
            if last["team"] == 1:
                match.team1_current_points = max(0, match.team1_current_points - 1)
            else:
                match.team2_current_points = max(0, match.team2_current_points - 1)
            match.point_history = json.dumps(history)
    
    elif update.action == "toggle_serve":
        if match.serve_team_id == match.team1_id:
            match.serve_team_id = match.team2_id
        else:
            match.serve_team_id = match.team1_id
    
    elif update.action == "set_won":
        # Record set points
        t1_set_points = json.loads(match.team1_set_points) if match.team1_set_points else []
        t2_set_points = json.loads(match.team2_set_points) if match.team2_set_points else []
        
        t1_set_points.append(match.team1_current_points)
        t2_set_points.append(match.team2_current_points)
        
        match.team1_set_points = json.dumps(t1_set_points)
        match.team2_set_points = json.dumps(t2_set_points)
        
        # Award set to winner
        if is_team1:
            match.team1_sets += 1
        else:
            match.team2_sets += 1
        
        # Reset current points and move to next set
        match.team1_current_points = 0
        match.team2_current_points = 0
        match.current_set += 1
        match.point_history = "[]"
    
    db.commit()
    
    # Broadcast update
    t1 = db.query(models.Team).filter(models.Team.id == match.team1_id).first()
    t2 = db.query(models.Team).filter(models.Team.id == match.team2_id).first()
    serve_team = db.query(models.Team).filter(models.Team.id == match.serve_team_id).first()
    
    await manager.broadcast({
        "event": "score_update",
        "sport": "volleyball",
        "match_id": match_id,
        "current_set": match.current_set,
        "serve_team": serve_team.name if serve_team else "TBA",
        "team1_score": {
            "name": t1.name if t1 else "Team 1",
            "sets": match.team1_sets,
            "current_points": match.team1_current_points,
            "set_points": json.loads(match.team1_set_points) if match.team1_set_points else []
        },
        "team2_score": {
            "name": t2.name if t2 else "Team 2",
            "sets": match.team2_sets,
            "current_points": match.team2_current_points,
            "set_points": json.loads(match.team2_set_points) if match.team2_set_points else []
        },
        "action": update.action
    }, match_id)

    return {
        "message": "Score updated",
        "team1_points": match.team1_current_points,
        "team2_points": match.team2_current_points,
        "team1_sets": match.team1_sets,
        "team2_sets": match.team2_sets
    }


# =============================================================================
# MATCH COMPLETION
# =============================================================================

@app.post("/api/matches/{match_id}/complete")
@app.put("/api/matches/{match_id}/complete")
@app.post("/api/matches/{match_id}/end_match")
async def end_match(
    match_id: int,
    db: Session = Depends(get_db)
):
    """End the match and calculate result (public endpoint for admin panel)"""
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    match.status = "COMPLETED"
    
    t1 = db.query(models.Team).filter(models.Team.id == match.team1_id).first()
    t2 = db.query(models.Team).filter(models.Team.id == match.team2_id).first()
    
    winner = None
    loser = None
    
    if match.sport == "cricket":
        first_innings_score = match.total_runs
        second_innings_score = match.innings2_runs
        
        if second_innings_score >= match.target:
            winner, loser = t2, t1
            wickets_remaining = 10 - match.innings2_wickets
            match.result = f"{t2.name} won by {wickets_remaining} wickets"
        else:
            winner, loser = t1, t2
            runs_difference = first_innings_score - second_innings_score
            match.result = f"{t1.name} won by {runs_difference} runs"
        
        # Update team stats
        if winner:
            winner.total_runs_scored += first_innings_score if winner == t1 else second_innings_score
            loser.total_runs_scored += second_innings_score if winner == t1 else first_innings_score
    
    elif match.sport == "kabaddi":
        team1_total = match.team1_raid_points + match.team1_tackle_points + (match.team1_all_outs * 2) + match.team1_bonus_points
        team2_total = match.team2_raid_points + match.team2_tackle_points + (match.team2_all_outs * 2) + match.team2_bonus_points
        
        if team1_total > team2_total:
            winner, loser = t1, t2
            match.result = f"{t1.name} won by {team1_total - team2_total} points"
        elif team2_total > team1_total:
            winner, loser = t2, t1
            match.result = f"{t2.name} won by {team2_total - team1_total} points"
        else:
            match.result = "Match tied"
        
        # Update team stats
        if t1:
            t1.total_raid_points += match.team1_raid_points
            t1.total_tackle_points += match.team1_tackle_points
        if t2:
            t2.total_raid_points += match.team2_raid_points
            t2.total_tackle_points += match.team2_tackle_points
    
    elif match.sport == "volleyball":
        if match.ttp_points > 0:  # TTP mode
            if match.team1_current_points > match.team2_current_points:
                winner, loser = t1, t2
                match.result = f"{t1.name} won {match.team1_current_points}-{match.team2_current_points}"
            else:
                winner, loser = t2, t1
                match.result = f"{t2.name} won {match.team2_current_points}-{match.team1_current_points}"
        else:  # Match mode
            if match.team1_sets > match.team2_sets:
                winner, loser = t1, t2
                match.result = f"{t1.name} won {match.team1_sets}-{match.team2_sets}"
            else:
                winner, loser = t2, t1
                match.result = f"{t2.name} won {match.team2_sets}-{match.team1_sets}"
        
        # Update team stats
        if t1:
            t1.total_sets_won += match.team1_sets
        if t2:
            t2.total_sets_won += match.team2_sets
    
    # Update team win/loss stats
    if winner and loser:
        winner.wins += 1
        winner.matches_played += 1
        winner.points += 2
        loser.losses += 1
        loser.matches_played += 1
    
    db.commit()
    
    # Broadcast match end
    await manager.broadcast({
        "event": "match_end",
        "match_id": match_id,
        "status": "COMPLETED",
        "result": match.result,
        "message": f"Match finished! {match.result}"
    }, match_id)
    
    return {"message": "Match completed", "result": match.result}


# =============================================================================
# ACHIEVEMENTS / LEADERBOARD
# =============================================================================

@app.get("/api/achievements")
def get_achievements(sport: Optional[str] = None, db: Session = Depends(get_db)):
    """Get achievements and leaderboard data"""
    result = {
        "top_teams": [],
        "recent_matches": [],
        "records": {}
    }
    
    sports_to_query = [sport] if sport else ["cricket", "kabaddi", "volleyball"]
    
    for s in sports_to_query:
        teams = db.query(models.Team).filter(models.Team.sport == s).order_by(models.Team.points.desc()).limit(5).all()
        
        for team in teams:
            result["top_teams"].append({
                "id": team.id,
                "name": team.name,
                "sport": team.sport,
                "wins": team.wins,
                "losses": team.losses,
                "points": team.points,
                "symbol": team.symbol
            })
        
        # Get sport-specific records
        if s == "cricket":
            top_scorer = db.query(models.Team).filter(models.Team.sport == "cricket").order_by(models.Team.total_runs_scored.desc()).first()
            result["records"]["cricket"] = {
                "highest_runs": {
                    "team": top_scorer.name if top_scorer else None,
                    "runs": top_scorer.total_runs_scored if top_scorer else 0
                }
            }
        elif s == "kabaddi":
            top_raider = db.query(models.Team).filter(models.Team.sport == "kabaddi").order_by(models.Team.total_raid_points.desc()).first()
            top_defender = db.query(models.Team).filter(models.Team.sport == "kabaddi").order_by(models.Team.total_tackle_points.desc()).first()
            result["records"]["kabaddi"] = {
                "most_raid_points": {
                    "team": top_raider.name if top_raider else None,
                    "points": top_raider.total_raid_points if top_raider else 0
                },
                "most_tackle_points": {
                    "team": top_defender.name if top_defender else None,
                    "points": top_defender.total_tackle_points if top_defender else 0
                }
            }
        elif s == "volleyball":
            top_sets = db.query(models.Team).filter(models.Team.sport == "volleyball").order_by(models.Team.total_sets_won.desc()).first()
            result["records"]["volleyball"] = {
                "most_sets_won": {
                    "team": top_sets.name if top_sets else None,
                    "sets": top_sets.total_sets_won if top_sets else 0
                }
            }
    
    # Recent completed matches
    recent = db.query(models.Match).filter(models.Match.status == "COMPLETED").order_by(models.Match.id.desc()).limit(10).all()
    for match in recent:
        t1 = db.query(models.Team).filter(models.Team.id == match.team1_id).first()
        t2 = db.query(models.Team).filter(models.Team.id == match.team2_id).first()
        result["recent_matches"].append({
            "id": match.id,
            "sport": match.sport,
            "team1": t1.name if t1 else "TBA",
            "team2": t2.name if t2 else "TBA",
            "result": match.result,
            "date": match.date
        })
    
    return result


# =============================================================================
# WEBSOCKET ENDPOINT
# =============================================================================

@app.websocket("/ws/matches/{match_id}")
async def websocket_endpoint(websocket: WebSocket, match_id: int):
    """WebSocket endpoint for live score updates"""
    await manager.connect(websocket, match_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Could handle ping/pong or chat here
    except WebSocketDisconnect:
        manager.disconnect(websocket, match_id)


# =============================================================================
# DEMO/ADMIN ENDPOINTS
# =============================================================================

@app.post("/api/matches/init_demo")
def init_demo_data(db: Session = Depends(get_db)):
    """Create demo teams for testing (no auth required)"""
    created_teams = []
    
    # Demo teams for each sport
    demo_teams = [
        # Cricket
        {"name": "Phoenix Warriors", "sport": "cricket", "captain": "Rohit", "symbol": "🦅",
         "players": json.dumps([{"name": "Rohit", "is_captain": True}] + [{"name": f"Player {i}", "is_captain": False} for i in range(2, 12)])},
        {"name": "Thunder Strikers", "sport": "cricket", "captain": "Virat", "symbol": "⚡",
         "players": json.dumps([{"name": "Virat", "is_captain": True}] + [{"name": f"Player {i}", "is_captain": False} for i in range(2, 12)])},
        # Kabaddi
        {"name": "Bengal Warriors", "sport": "kabaddi", "captain": "Maninder", "symbol": "🐯",
         "players": json.dumps([{"name": "Maninder", "is_captain": True}] + [{"name": f"Player {i}", "is_captain": False} for i in range(2, 8)])},
        {"name": "Patna Pirates", "sport": "kabaddi", "captain": "Pardeep", "symbol": "☠️",
         "players": json.dumps([{"name": "Pardeep", "is_captain": True}] + [{"name": f"Player {i}", "is_captain": False} for i in range(2, 8)])},
        # Volleyball
        {"name": "Chennai Spikers", "sport": "volleyball", "captain": "Ajith", "symbol": "🌊",
         "players": json.dumps([{"name": "Ajith", "is_captain": True}] + [{"name": f"Player {i}", "is_captain": False} for i in range(2, 7)])},
        {"name": "Mumbai Blockers", "sport": "volleyball", "captain": "Sachin", "symbol": "🛡️",
         "players": json.dumps([{"name": "Sachin", "is_captain": True}] + [{"name": f"Player {i}", "is_captain": False} for i in range(2, 7)])}
    ]
    
    for team_data in demo_teams:
        existing = db.query(models.Team).filter(models.Team.name == team_data["name"]).first()
        if not existing:
            color_start, color_end = get_sport_colors(team_data["sport"])
            team = models.Team(
                name=team_data["name"],
                sport=team_data["sport"],
                captain=team_data["captain"],
                phone="123456789",
                email=f"{team_data['name'].lower().replace(' ', '')}@demo.com",
                players=team_data["players"],
                location="India",
                experience="Professional",
                symbol=team_data["symbol"],
                logo_color_start=color_start,
                logo_color_end=color_end
            )
            db.add(team)
            created_teams.append(team_data["name"])
    
    db.commit()
    
    if created_teams:
        return {"message": f"Demo teams created: {', '.join(created_teams)}"}
    return {"message": "Demo teams already exist"}


@app.get("/")
def root():
    """API root endpoint"""
    return {
        "name": "Sports Arena API",
        "version": "2.0",
        "sports": ["cricket", "kabaddi", "volleyball"],
        "docs": "/docs"
    }