from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import random
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone
from french_words import get_words_list, normalize_word, get_original_word, WORDS_BY_LENGTH

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# In-memory storage for custom word lists per session
custom_word_lists: Dict[str, List[str]] = {}

# Models
class GridConfig(BaseModel):
    rows: int = Field(ge=5, le=20)
    cols: int = Field(ge=5, le=20)
    first_horizontal_word: str
    first_vertical_word: str
    session_id: Optional[str] = None

class GridState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    rows: int
    cols: int
    grid: List[List[str]]  # "" = empty, "#" = blocked, letter = filled
    words_placed: List[Dict[str, Any]]  # [{word, direction, row, col}]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class WordProposal(BaseModel):
    word: str
    original_word: str  # With accents
    direction: str  # "horizontal" or "vertical"
    row: int
    col: int
    length: int

class ProposeWordRequest(BaseModel):
    grid_state: Dict[str, Any]
    direction: str  # "horizontal" or "vertical"
    session_id: Optional[str] = None

class PlaceWordRequest(BaseModel):
    grid_state: Dict[str, Any]
    word: str
    direction: str
    row: int
    col: int

class RejectWordRequest(BaseModel):
    grid_state: Dict[str, Any]
    direction: str
    rejected_words: List[str]
    session_id: Optional[str] = None

# Helper functions
def create_empty_grid(rows: int, cols: int) -> List[List[str]]:
    """Create an empty grid"""
    return [["" for _ in range(cols)] for _ in range(rows)]

def can_place_word(grid: List[List[str]], word: str, row: int, col: int, direction: str) -> bool:
    """Check if a word can be placed at the given position"""
    rows = len(grid)
    cols = len(grid[0])
    
    if direction == "horizontal":
        if col + len(word) > cols:
            return False
        for i, letter in enumerate(word):
            cell = grid[row][col + i]
            if cell == "#":
                return False
            if cell != "" and cell != letter:
                return False
    else:  # vertical
        if row + len(word) > rows:
            return False
        for i, letter in enumerate(word):
            cell = grid[row + i][col]
            if cell == "#":
                return False
            if cell != "" and cell != letter:
                return False
    
    return True

def place_word(grid: List[List[str]], word: str, row: int, col: int, direction: str) -> List[List[str]]:
    """Place a word on the grid and add blocking cells"""
    new_grid = [row_data[:] for row_data in grid]
    rows = len(grid)
    cols = len(grid[0])
    
    if direction == "horizontal":
        # Place the word
        for i, letter in enumerate(word):
            new_grid[row][col + i] = letter
        # Add blocking cell after the word if space available
        end_col = col + len(word)
        if end_col < cols and new_grid[row][end_col] == "":
            new_grid[row][end_col] = "#"
        # Add blocking cell before the word if space available
        if col > 0 and new_grid[row][col - 1] == "":
            new_grid[row][col - 1] = "#"
    else:  # vertical
        # Place the word
        for i, letter in enumerate(word):
            new_grid[row + i][col] = letter
        # Add blocking cell after the word if space available
        end_row = row + len(word)
        if end_row < rows and new_grid[end_row][col] == "":
            new_grid[end_row][col] = "#"
        # Add blocking cell before the word if space available
        if row > 0 and new_grid[row - 1][col] == "":
            new_grid[row - 1][col] = "#"
    
    return new_grid

def find_word_positions(grid: List[List[str]], direction: str) -> List[Dict[str, Any]]:
    """Find all possible positions where a word could be placed"""
    rows = len(grid)
    cols = len(grid[0])
    positions = []
    
    if direction == "horizontal":
        for row in range(rows):
            for col in range(cols):
                # Check if we can start a word here
                if col == 0 or grid[row][col - 1] == "#":
                    # Find the pattern (letters and empty cells)
                    pattern = []
                    end_col = col
                    while end_col < cols and grid[row][end_col] != "#":
                        pattern.append(grid[row][end_col])
                        end_col += 1
                    
                    if len(pattern) >= 2:
                        # Check if there's at least one letter constraint
                        has_letter = any(c != "" for c in pattern)
                        if has_letter:
                            positions.append({
                                "row": row,
                                "col": col,
                                "pattern": pattern,
                                "max_length": len(pattern)
                            })
    else:  # vertical
        for col in range(cols):
            for row in range(rows):
                # Check if we can start a word here
                if row == 0 or grid[row - 1][col] == "#":
                    # Find the pattern (letters and empty cells)
                    pattern = []
                    end_row = row
                    while end_row < rows and grid[end_row][col] != "#":
                        pattern.append(grid[end_row][col])
                        end_row += 1
                    
                    if len(pattern) >= 2:
                        # Check if there's at least one letter constraint
                        has_letter = any(c != "" for c in pattern)
                        if has_letter:
                            positions.append({
                                "row": row,
                                "col": col,
                                "pattern": pattern,
                                "max_length": len(pattern)
                            })
    
    return positions

def word_matches_pattern(word: str, pattern: List[str]) -> bool:
    """Check if a word matches a pattern (letters must match, empty cells accept any letter)"""
    if len(word) > len(pattern):
        return False
    
    for i, letter in enumerate(word):
        if pattern[i] != "" and pattern[i] != letter:
            return False
    
    return True

def find_matching_words(pattern: List[str], words_list: List[str], excluded: List[str], max_results: int = 50) -> List[str]:
    """Find words that match the pattern, sorted by length (longest first)"""
    matching = []
    max_len = len(pattern)
    
    for word in words_list:
        if len(word) > max_len:
            continue
        if len(word) < 2:
            continue
        if word in excluded:
            continue
        if word_matches_pattern(word, pattern):
            matching.append(word)
            if len(matching) >= max_results:
                break
    
    return matching

def get_word_list(session_id: Optional[str]) -> List[str]:
    """Get the word list for a session (custom or default)"""
    if session_id and session_id in custom_word_lists:
        return custom_word_lists[session_id]
    return WORDS_BY_LENGTH

# API Routes
@api_router.get("/")
async def root():
    return {"message": "Générateur de Mots Croisés API"}

@api_router.post("/crossword/init")
async def init_crossword(config: GridConfig):
    """Initialize a new crossword grid with first horizontal and vertical words"""
    
    # Normalize words
    h_word = normalize_word(config.first_horizontal_word.strip())
    v_word = normalize_word(config.first_vertical_word.strip())
    
    if len(h_word) < 2 or len(v_word) < 2:
        raise HTTPException(status_code=400, detail="Les mots doivent avoir au moins 2 lettres")
    
    if len(h_word) > config.cols:
        raise HTTPException(status_code=400, detail=f"Le mot horizontal est trop long pour {config.cols} colonnes")
    
    if len(v_word) > config.rows:
        raise HTTPException(status_code=400, detail=f"Le mot vertical est trop long pour {config.rows} lignes")
    
    # Find intersection point
    intersection = None
    for i, h_letter in enumerate(h_word):
        for j, v_letter in enumerate(v_word):
            if h_letter == v_letter:
                intersection = (i, j)
                break
        if intersection:
            break
    
    if not intersection:
        raise HTTPException(
            status_code=400, 
            detail="Les mots doivent avoir au moins une lettre en commun pour se croiser"
        )
    
    h_pos, v_pos = intersection
    
    # Calculate positions - place horizontal word at row 0 or centered
    h_row = v_pos  # Vertical word starts at row 0, so horizontal crosses at v_pos
    h_col = 0
    
    # Ensure horizontal word fits
    if h_col + len(h_word) > config.cols:
        h_col = config.cols - len(h_word)
    
    # Calculate vertical word position
    v_row = 0
    v_col = h_col + h_pos  # Column where intersection happens
    
    # Create grid and place words
    grid = create_empty_grid(config.rows, config.cols)
    
    # Place horizontal word
    grid = place_word(grid, h_word, h_row, h_col, "horizontal")
    
    # Place vertical word (this will overwrite the intersection which is fine)
    grid = place_word(grid, v_word, v_row, v_col, "vertical")
    
    words_placed = [
        {
            "word": h_word,
            "original": get_original_word(h_word),
            "direction": "horizontal",
            "row": h_row,
            "col": h_col
        },
        {
            "word": v_word,
            "original": get_original_word(v_word),
            "direction": "vertical",
            "row": v_row,
            "col": v_col
        }
    ]
    
    return {
        "grid": grid,
        "rows": config.rows,
        "cols": config.cols,
        "words_placed": words_placed,
        "message": "Grille initialisée avec succès"
    }

@api_router.post("/crossword/propose")
async def propose_word(request: ProposeWordRequest):
    """Propose a new word based on existing letters"""
    
    grid = request.grid_state.get("grid", [])
    direction = request.direction
    
    if not grid:
        raise HTTPException(status_code=400, detail="Grille invalide")
    
    # Find possible positions
    positions = find_word_positions(grid, direction)
    
    if not positions:
        return {
            "proposal": None,
            "message": f"Aucune position disponible pour un mot {direction}"
        }
    
    # Get word list
    words_list = get_word_list(request.session_id)
    
    # Get already placed words
    placed_words = [w.get("word", "") for w in request.grid_state.get("words_placed", [])]
    
    # Try each position and find matching words
    all_proposals = []
    
    for pos in positions:
        matching = find_matching_words(pos["pattern"], words_list, placed_words, max_results=20)
        for word in matching:
            # Skip if word is already placed
            if word not in placed_words:
                all_proposals.append({
                    "word": word,
                    "original_word": get_original_word(word),
                    "direction": direction,
                    "row": pos["row"],
                    "col": pos["col"],
                    "length": len(word)
                })
    
    if not all_proposals:
        return {
            "proposal": None,
            "message": f"Aucun mot trouvé pour la direction {direction}"
        }
    
    # Sort by length (longest first) and pick a random one from top candidates
    all_proposals.sort(key=lambda x: -x["length"])
    
    # Take top 10 longest and pick randomly
    top_proposals = all_proposals[:10]
    proposal = random.choice(top_proposals)
    
    return {
        "proposal": proposal,
        "message": f"Mot proposé: {proposal['original_word']}"
    }

@api_router.post("/crossword/reject")
async def reject_and_propose(request: RejectWordRequest):
    """Reject current word and propose a new one"""
    
    grid = request.grid_state.get("grid", [])
    direction = request.direction
    rejected = [normalize_word(w) for w in request.rejected_words]
    
    if not grid:
        raise HTTPException(status_code=400, detail="Grille invalide")
    
    # Find possible positions
    positions = find_word_positions(grid, direction)
    
    if not positions:
        return {
            "proposal": None,
            "message": f"Aucune position disponible pour un mot {direction}"
        }
    
    # Get word list
    words_list = get_word_list(request.session_id)
    
    # Get already placed words + rejected words
    placed_words = [w.get("word", "") for w in request.grid_state.get("words_placed", [])]
    excluded = placed_words + rejected
    
    # Try each position and find matching words
    all_proposals = []
    
    for pos in positions:
        matching = find_matching_words(pos["pattern"], words_list, excluded, max_results=30)
        for word in matching:
            all_proposals.append({
                "word": word,
                "original_word": get_original_word(word),
                "direction": direction,
                "row": pos["row"],
                "col": pos["col"],
                "length": len(word)
            })
    
    if not all_proposals:
        return {
            "proposal": None,
            "message": f"Plus de mots disponibles pour la direction {direction}"
        }
    
    # Sort by length (longest first) and pick a random one from top candidates
    all_proposals.sort(key=lambda x: -x["length"])
    
    # Take top 10 longest and pick randomly
    top_proposals = all_proposals[:10]
    proposal = random.choice(top_proposals)
    
    return {
        "proposal": proposal,
        "message": f"Nouveau mot proposé: {proposal['original_word']}"
    }

@api_router.post("/crossword/place")
async def place_word_on_grid(request: PlaceWordRequest):
    """Place a word on the grid"""
    
    grid = request.grid_state.get("grid", [])
    word = normalize_word(request.word)
    
    if not grid:
        raise HTTPException(status_code=400, detail="Grille invalide")
    
    # Check if word can be placed
    if not can_place_word(grid, word, request.row, request.col, request.direction):
        raise HTTPException(status_code=400, detail="Le mot ne peut pas être placé à cette position")
    
    # Place the word
    new_grid = place_word(grid, word, request.row, request.col, request.direction)
    
    # Update words placed
    words_placed = request.grid_state.get("words_placed", [])
    words_placed.append({
        "word": word,
        "original": get_original_word(word),
        "direction": request.direction,
        "row": request.row,
        "col": request.col
    })
    
    return {
        "grid": new_grid,
        "words_placed": words_placed,
        "message": f"Mot '{get_original_word(word)}' placé avec succès"
    }

@api_router.post("/words/upload")
async def upload_word_list(file: UploadFile = File(...)):
    """Upload a custom word list"""
    
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Le fichier doit être un fichier .txt")
    
    try:
        content = await file.read()
        text = content.decode('utf-8')
        
        # Parse words (one per line)
        words = []
        for line in text.split('\n'):
            word = line.strip()
            if word and len(word) >= 2:
                normalized = normalize_word(word)
                if normalized.isalpha():
                    words.append(normalized)
        
        if len(words) < 10:
            raise HTTPException(status_code=400, detail="Le fichier doit contenir au moins 10 mots valides")
        
        # Sort by length (longest first)
        words = sorted(list(set(words)), key=lambda x: -len(x))
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        custom_word_lists[session_id] = words
        
        return {
            "session_id": session_id,
            "word_count": len(words),
            "message": f"{len(words)} mots chargés avec succès"
        }
        
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Erreur de décodage du fichier. Utilisez l'encodage UTF-8.")

@api_router.get("/words/count")
async def get_word_count(session_id: Optional[str] = None):
    """Get the count of words in the current list"""
    words_list = get_word_list(session_id)
    return {
        "count": len(words_list),
        "is_custom": session_id is not None and session_id in custom_word_lists
    }

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
