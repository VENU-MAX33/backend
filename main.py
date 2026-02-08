from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import json
from datetime import datetime

# Appwrite SDK
from appwrite.client import Client
from appwrite.services.databases import Databases
from appwrite.id import ID
from appwrite.query import Query

# Import Appwrite configuration
from appwrite_config import (
    APPWRITE_ENDPOINT,
    APPWRITE_PROJECT_ID,
    APPWRITE_DATABASE_ID,
    APPWRITE_API_KEY,
    COLLECTIONS
)

# =============================================================================
# APPWRITE CLIENT SETUP
# =============================================================================

client = Client()
client.set_endpoint(APPWRITE_ENDPOINT)
client.set_project(APPWRITE_PROJECT_ID)
client.set_key(APPWRITE_API_KEY)  # API key for server-side operations

databases = Databases(client)

# =============================================================================
# FASTAPI APP SETUP
# =============================================================================

app = FastAPI(
    title="Sports Arena API - Appwrite Edition",
    description="Multi-sport live scoring platform connected to Appwrite"
)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class PlayerInfo(BaseModel):
    name: str
    age: Optional[int] = None
    registerNo: Optional[str] = None
    isCaptain: bool = False


class SimpleTeamCreate(BaseModel):
    name: str
    sport: str = "cricket"
    captain: Optional[str] = None
    players: List[PlayerInfo]


class MatchCreate(BaseModel):
    team1_id: str
    team2_id: str
    team1_name: str
    team2_name: str
    sport: str = "cricket"
    venue: str = "Sports Arena"
    admin_name: Optional[str] = "Admin"
    umpire_name: Optional[str] = "Umpire"
    total_overs: Optional[int] = 20


class ScoreUpdate(BaseModel):
    match_id: str
    team_id: str
    runs: Optional[int] = 0
    wickets: Optional[int] = 0
    overs: Optional[float] = 0.0
    extras: Optional[int] = 0
    action: Optional[str] = None  # For kabaddi/volleyball


class AchievementCreate(BaseModel):
    match_id: str
    player_name: str
    achievement_type: str  # "man_of_match", "best_bowler", "best_batsman", etc.
    description: str


# =============================================================================
# WEBSOCKET MANAGER FOR LIVE UPDATES
# =============================================================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, match_id: str):
        await websocket.accept()
        if match_id not in self.active_connections:
            self.active_connections[match_id] = []
        self.active_connections[match_id].append(websocket)

    def disconnect(self, websocket: WebSocket, match_id: str):
        if match_id in self.active_connections:
            if websocket in self.active_connections[match_id]:
                self.active_connections[match_id].remove(websocket)

    async def broadcast(self, message: dict, match_id: str):
        if match_id in self.active_connections:
            for connection in self.active_connections[match_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    print(f"Error sending message: {e}")


manager = ConnectionManager()


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/")
def root():
    return {
        "message": "Sports Arena API - Appwrite Edition",
        "status": "running",
        "database": "Appwrite",
        "endpoints": [
            "/api/teams",
            "/api/teams/register",
            "/api/matches",
            "/api/matches/create",
            "/api/matches/{match_id}/score",
            "/api/achievements"
        ]
    }


# =============================================================================
# TEAM ENDPOINTS
# =============================================================================

@app.post("/api/teams/register")
@app.post("/api/teams")
def register_team(team: SimpleTeamCreate):
    """Register a new team to Appwrite"""
    try:
        # Prepare players data
        players_data = []
        captain_name = team.captain
        
        for p in team.players:
            player_dict = {
                "name": p.name,
                "is_captain": p.isCaptain
            }
            if p.age:
                player_dict["age"] = p.age
            if p.registerNo:
                player_dict["register_no"] = p.registerNo
            players_data.append(player_dict)
            
            if p.isCaptain and not captain_name:
                captain_name = p.name
        
        if not captain_name and players_data:
            captain_name = players_data[0]["name"]
        
        # Convert players to a short comma-separated string (Appwrite string limit)
        players_str = ", ".join([p.name for p in team.players])
        
        # Create document in Appwrite 'teams' collection
        response = databases.create_document(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["teams"],
            document_id=ID.unique(),
            data={
                "name": team.name,
                "sport": team.sport,
                "captain": captain_name or "",
                "players": players_str,  # Short string, NOT json.dumps
                "wins": 0,
                "losses": 0,
                "matches_played": 0,
                "points": 0,
                "created_at": datetime.now().isoformat()
            }
        )
        
        return {
            "id": response["$id"],
            "message": f"{team.sport.title()} team '{team.name}' registered successfully!"
        }
        
    except Exception as e:
        print(f"Error registering team: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/teams")
def get_teams(sport: Optional[str] = None):
    """Get all teams from Appwrite"""
    try:
        queries = []
        if sport:
            queries.append(Query.equal("sport", sport))
        
        response = databases.list_documents(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["teams"],
            queries=queries
        )
        
        teams = []
        for doc in response["documents"]:
            teams.append({
                "id": doc["$id"],
                "name": doc.get("name", ""),
                "sport": doc.get("sport", "cricket"),
                "captain": doc.get("captain", ""),
                "players": doc.get("players", "[]"),
                "wins": doc.get("wins", 0),
                "losses": doc.get("losses", 0),
                "matches_played": doc.get("matches_played", 0),
                "points": doc.get("points", 0)
            })
        
        return teams
        
    except Exception as e:
        print(f"Error fetching teams: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/teams/{team_id}")
def get_team(team_id: str):
    """Get a specific team by ID"""
    try:
        response = databases.get_document(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["teams"],
            document_id=team_id
        )
        
        return {
            "id": response["$id"],
            "name": response.get("name", ""),
            "sport": response.get("sport", "cricket"),
            "captain": response.get("captain", ""),
            "players": response.get("players", "[]"),
            "wins": response.get("wins", 0),
            "losses": response.get("losses", 0),
            "matches_played": response.get("matches_played", 0),
            "points": response.get("points", 0)
        }
        
    except Exception as e:
        print(f"Error fetching team: {e}")
        raise HTTPException(status_code=404, detail="Team not found")


# =============================================================================
# MATCH ENDPOINTS
# =============================================================================

@app.post("/api/matches/create")
@app.post("/api/matches")
def create_match(match: MatchCreate):
    """Create a new match in Appwrite"""
    try:
        response = databases.create_document(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["matches"],
            document_id=ID.unique(),
            data={
                "sport": match.sport,
                "team1_id": match.team1_id,
                "team2_id": match.team2_id,
                "team1_name": match.team1_name,
                "team2_name": match.team2_name,
                "venue": match.venue,
                "admin_name": match.admin_name,
                "umpire_name": match.umpire_name,
                "total_overs": match.total_overs,
                "status": "UPCOMING",
                "team1_score": 0,
                "team1_wickets": 0,
                "team1_overs": 0,
                "team2_score": 0,
                "team2_wickets": 0,
                "team2_overs": 0,
                "current_innings": 1,
                "result": "",
                "created_at": datetime.now().isoformat()
            }
        )
        
        return {
            "id": response["$id"],
            "message": f"Match created: {match.team1_name} vs {match.team2_name}",
            "match_id": response["$id"]
        }
        
    except Exception as e:
        print(f"Error creating match: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/matches")
def get_matches(sport: Optional[str] = None, status: Optional[str] = None):
    """Get all matches from Appwrite"""
    try:
        queries = []
        if sport:
            queries.append(Query.equal("sport", sport))
        if status:
            queries.append(Query.equal("status", status))
        
        response = databases.list_documents(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["matches"],
            queries=queries
        )
        
        matches = []
        for doc in response["documents"]:
            matches.append({
                "id": doc["$id"],
                "sport": doc.get("sport", "cricket"),
                "team1_id": doc.get("team1_id", ""),
                "team2_id": doc.get("team2_id", ""),
                "team1_name": doc.get("team1_name", "Team 1"),
                "team2_name": doc.get("team2_name", "Team 2"),
                "venue": doc.get("venue", ""),
                "status": doc.get("status", "UPCOMING"),
                "team1_score": doc.get("team1_score", 0),
                "team1_wickets": doc.get("team1_wickets", 0),
                "team2_score": doc.get("team2_score", 0),
                "team2_wickets": doc.get("team2_wickets", 0),
                "result": doc.get("result", ""),
                "score_summary": f"{doc.get('team1_score', 0)}/{doc.get('team1_wickets', 0)}"
            })
        
        return matches
        
    except Exception as e:
        print(f"Error fetching matches: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/matches/{match_id}")
def get_match(match_id: str):
    """Get match details by ID"""
    try:
        response = databases.get_document(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["matches"],
            document_id=match_id
        )
        
        return {
            "id": response["$id"],
            "sport": response.get("sport", "cricket"),
            "team1": {
                "id": response.get("team1_id", ""),
                "name": response.get("team1_name", "Team 1"),
                "score": response.get("team1_score", 0),
                "wickets": response.get("team1_wickets", 0),
                "overs": response.get("team1_overs", 0)
            },
            "team2": {
                "id": response.get("team2_id", ""),
                "name": response.get("team2_name", "Team 2"),
                "score": response.get("team2_score", 0),
                "wickets": response.get("team2_wickets", 0),
                "overs": response.get("team2_overs", 0)
            },
            "venue": response.get("venue", ""),
            "status": response.get("status", "UPCOMING"),
            "current_innings": response.get("current_innings", 1),
            "total_overs": response.get("total_overs", 20),
            "result": response.get("result", ""),
            "is_admin": True
        }
        
    except Exception as e:
        print(f"Error fetching match: {e}")
        raise HTTPException(status_code=404, detail="Match not found")


@app.post("/api/matches/{match_id}/start")
def start_match(match_id: str):
    """Start a match"""
    try:
        response = databases.update_document(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["matches"],
            document_id=match_id,
            data={"status": "LIVE"}
        )
        
        return {"message": "Match started", "status": "LIVE"}
        
    except Exception as e:
        print(f"Error starting match: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# LIVE SCORE ENDPOINTS
# =============================================================================

@app.post("/api/matches/{match_id}/score")
@app.put("/api/matches/{match_id}/score")
async def update_score(match_id: str, score: ScoreUpdate):
    """Update match score in Appwrite and broadcast to WebSocket clients"""
    try:
        # Get current match data
        match = databases.get_document(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["matches"],
            document_id=match_id
        )
        
        # Determine which team to update
        update_data = {}
        if score.team_id == match.get("team1_id"):
            update_data = {
                "team1_score": match.get("team1_score", 0) + score.runs,
                "team1_wickets": match.get("team1_wickets", 0) + score.wickets,
                "team1_overs": score.overs if score.overs else match.get("team1_overs", 0)
            }
        else:
            update_data = {
                "team2_score": match.get("team2_score", 0) + score.runs,
                "team2_wickets": match.get("team2_wickets", 0) + score.wickets,
                "team2_overs": score.overs if score.overs else match.get("team2_overs", 0)
            }
        
        # Update in Appwrite
        response = databases.update_document(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["matches"],
            document_id=match_id,
            data=update_data
        )
        
        # Also create a live_score entry for real-time tracking
        try:
            databases.create_document(
                database_id=APPWRITE_DATABASE_ID,
                collection_id=COLLECTIONS["live_scores"],
                document_id=ID.unique(),
                data={
                    "match_id": match_id,
                    "team_id": score.team_id,
                    "runs": score.runs,
                    "wickets": score.wickets,
                    "overs": score.overs,
                    "action": score.action or "score_update",
                    "timestamp": datetime.now().isoformat()
                }
            )
        except Exception as e:
            print(f"Warning: Could not create live_score entry: {e}")
        
        # Broadcast to WebSocket clients
        await manager.broadcast({
            "event": "score_update",
            "match_id": match_id,
            "team_id": score.team_id,
            "runs_added": score.runs,
            "wickets_added": score.wickets,
            "current_score": update_data
        }, match_id)
        
        return {
            "message": "Score updated successfully",
            "score": update_data
        }
        
    except Exception as e:
        print(f"Error updating score: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/matches/{match_id}/end")
def end_match(match_id: str, result: str = ""):
    """End a match and set the result"""
    try:
        response = databases.update_document(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["matches"],
            document_id=match_id,
            data={
                "status": "COMPLETED",
                "result": result
            }
        )
        
        return {"message": "Match ended", "result": result}
        
    except Exception as e:
        print(f"Error ending match: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# ACHIEVEMENTS ENDPOINTS
# =============================================================================

@app.post("/api/achievements")
def create_achievement(achievement: AchievementCreate):
    """Create an achievement in Appwrite"""
    try:
        response = databases.create_document(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["achievements"],
            document_id=ID.unique(),
            data={
                "match_id": achievement.match_id,
                "player_name": achievement.player_name,
                "achievement_type": achievement.achievement_type,
                "description": achievement.description,
                "created_at": datetime.now().isoformat()
            }
        )
        
        return {
            "id": response["$id"],
            "message": f"Achievement '{achievement.achievement_type}' awarded to {achievement.player_name}"
        }
        
    except Exception as e:
        print(f"Error creating achievement: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/achievements")
def get_achievements(match_id: Optional[str] = None, player_name: Optional[str] = None):
    """Get achievements from Appwrite"""
    try:
        queries = []
        if match_id:
            queries.append(Query.equal("match_id", match_id))
        if player_name:
            queries.append(Query.equal("player_name", player_name))
        
        response = databases.list_documents(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["achievements"],
            queries=queries
        )
        
        achievements = []
        for doc in response["documents"]:
            achievements.append({
                "id": doc["$id"],
                "match_id": doc.get("match_id", ""),
                "player_name": doc.get("player_name", ""),
                "achievement_type": doc.get("achievement_type", ""),
                "description": doc.get("description", ""),
                "created_at": doc.get("created_at", "")
            })
        
        return achievements
        
    except Exception as e:
        print(f"Error fetching achievements: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# REGISTRATIONS ENDPOINTS (for compatibility with frontend)
# =============================================================================

@app.get("/api/registrations")
def get_registrations():
    """Get all registrations from Appwrite"""
    try:
        response = databases.list_documents(
            database_id=APPWRITE_DATABASE_ID,
            collection_id=COLLECTIONS["registrations"]
        )
        
        registrations = []
        for doc in response["documents"]:
            registrations.append({
                "id": doc["$id"],
                "name": doc.get("name", ""),
                "email": doc.get("email", ""),
                "phone": doc.get("phone", ""),
                "team_id": doc.get("team_id", ""),
                "players_list": doc.get("players_list", []),
                "captain": doc.get("captain", ""),
                "status": doc.get("status", "pending")
            })
        
        return registrations
        
    except Exception as e:
        print(f"Error fetching registrations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WEBSOCKET FOR LIVE UPDATES
# =============================================================================

@app.websocket("/ws/{match_id}")
async def websocket_endpoint(websocket: WebSocket, match_id: str):
    await manager.connect(websocket, match_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo back or handle commands
            await websocket.send_json({"received": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket, match_id)


# =============================================================================
# RUN SERVER
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Sports Arena API - Appwrite Edition")
    print(f"📡 Appwrite Endpoint: {APPWRITE_ENDPOINT}")
    print(f"📁 Database ID: {APPWRITE_DATABASE_ID}")
    uvicorn.run(app, host="0.0.0.0", port=8000)