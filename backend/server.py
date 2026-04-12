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

# In-memory storage for priority word lists per session
priority_word_lists: Dict[str, List[str]] = {}
# Store original forms for priority words
priority_word_originals: Dict[str, Dict[str, str]] = {}

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
    """Place a word on the grid and add blocking cells before and after if cells are free"""
    new_grid = [row_data[:] for row_data in grid]
    rows = len(grid)
    cols = len(grid[0])
    
    if direction == "horizontal":
        # Place the word first
        for i, letter in enumerate(word):
            new_grid[row][col + i] = letter
        
        # Add blocking cell AFTER the word if:
        # - There is space (not at edge)
        # - The cell is empty (not a letter or already blocked)
        end_col = col + len(word)
        if end_col < cols:
            cell_after = new_grid[row][end_col]
            if cell_after == "":
                new_grid[row][end_col] = "#"
        
        # Add blocking cell BEFORE the word if:
        # - There is space (not at edge)
        # - The cell is empty (not a letter or already blocked)
        if col > 0:
            cell_before = new_grid[row][col - 1]
            if cell_before == "":
                new_grid[row][col - 1] = "#"
                
    else:  # vertical
        # Place the word first
        for i, letter in enumerate(word):
            new_grid[row + i][col] = letter
        
        # Add blocking cell AFTER the word if:
        # - There is space (not at edge)
        # - The cell is empty (not a letter or already blocked)
        end_row = row + len(word)
        if end_row < rows:
            cell_after = new_grid[end_row][col]
            if cell_after == "":
                new_grid[end_row][col] = "#"
        
        # Add blocking cell BEFORE the word if:
        # - There is space (not at edge)
        # - The cell is empty (not a letter or already blocked)
        if row > 0:
            cell_before = new_grid[row - 1][col]
            if cell_before == "":
                new_grid[row - 1][col] = "#"
    
    return new_grid

def validate_cross_direction(grid: List[List[str]], placed_direction: str, words_list: List[str]) -> List[List[str]]:
    """After placing a word, check the perpendicular direction for invalid letter groups.
    For each column (if placed horizontal) or row (if placed vertical),
    find groups of 3+ consecutive letters. If no valid word exists for that group,
    encadre it with black cells (before and after, if not already # or grid edge)."""
    new_grid = [row_data[:] for row_data in grid]
    rows = len(grid)
    cols = len(grid[0])
    
    if placed_direction == "horizontal":
        # Check all COLUMNS vertically
        for col in range(cols):
            groups = _find_letter_groups_in_col(new_grid, col, rows)
            for group in groups:
                if group["length"] >= 3:
                    # Build pattern for this vertical group
                    pattern = []
                    for r in range(group["start"], group["start"] + group["length"]):
                        pattern.append(new_grid[r][col])
                    
                    # Check if any word matches this pattern
                    has_valid = _pattern_has_valid_word(pattern, words_list)
                    
                    if not has_valid:
                        # Encadre with black cells
                        start_r = group["start"]
                        end_r = group["start"] + group["length"] - 1
                        # Black cell BEFORE the group
                        if start_r > 0 and new_grid[start_r - 1][col] == "":
                            new_grid[start_r - 1][col] = "#"
                        # Black cell AFTER the group
                        if end_r + 1 < rows and new_grid[end_r + 1][col] == "":
                            new_grid[end_r + 1][col] = "#"
    
    else:  # placed vertical -> check all ROWS horizontally
        for row in range(rows):
            groups = _find_letter_groups_in_row(new_grid, row, cols)
            for group in groups:
                if group["length"] >= 3:
                    pattern = []
                    for c in range(group["start"], group["start"] + group["length"]):
                        pattern.append(new_grid[row][c])
                    
                    has_valid = _pattern_has_valid_word(pattern, words_list)
                    
                    if not has_valid:
                        start_c = group["start"]
                        end_c = group["start"] + group["length"] - 1
                        if start_c > 0 and new_grid[row][start_c - 1] == "":
                            new_grid[row][start_c - 1] = "#"
                        if end_c + 1 < cols and new_grid[row][end_c + 1] == "":
                            new_grid[row][end_c + 1] = "#"
    
    return new_grid

def _find_letter_groups_in_col(grid: List[List[str]], col: int, rows: int) -> List[Dict]:
    """Find groups of consecutive letters (no empty, no #) in a column."""
    groups = []
    start = None
    for r in range(rows):
        cell = grid[r][col]
        if cell != "" and cell != "#":
            if start is None:
                start = r
        else:
            if start is not None:
                length = r - start
                if length >= 3:
                    groups.append({"start": start, "length": length})
                start = None
    # Don't forget trailing group
    if start is not None:
        length = rows - start
        if length >= 3:
            groups.append({"start": start, "length": length})
    return groups

def _find_letter_groups_in_row(grid: List[List[str]], row: int, cols: int) -> List[Dict]:
    """Find groups of consecutive letters (no empty, no #) in a row."""
    groups = []
    start = None
    for c in range(cols):
        cell = grid[row][c]
        if cell != "" and cell != "#":
            if start is None:
                start = c
        else:
            if start is not None:
                length = c - start
                if length >= 3:
                    groups.append({"start": start, "length": length})
                start = None
    if start is not None:
        length = cols - start
        if length >= 3:
            groups.append({"start": start, "length": length})
    return groups

def _pattern_has_valid_word(pattern: List[str], words_list: List[str]) -> bool:
    """Check if at least one word in the list matches this exact pattern (same length)."""
    pat_len = len(pattern)
    for word in words_list:
        if len(word) != pat_len:
            continue
        match = True
        for i, letter in enumerate(word):
            if pattern[i] != letter:
                match = False
                break
        if match:
            return True
    return False

def fill_black_after_letters(grid: List[List[str]], direction: str, target_row: int = None, target_col: int = None) -> List[List[str]]:
    """When no word can be placed, put a black cell after the first group of
    consecutive letters on the target row/col. Leaves other letters untouched
    so they can serve as starting points for future longer words."""
    new_grid = [row_data[:] for row_data in grid]
    rows = len(grid)
    cols = len(grid[0])
    
    if direction == "horizontal" and target_row is not None and 0 <= target_row < rows:
        row = target_row
        # Scan from left: find the first consecutive group of letters
        in_group = False
        last_letter_col = -1
        for col in range(cols):
            cell = new_grid[row][col]
            if cell == "#":
                if in_group:
                    break  # group ended by existing #
                continue  # skip leading #
            if cell != "":  # it's a letter
                in_group = True
                last_letter_col = col
            else:  # empty cell
                if in_group:
                    break  # first empty cell after letters = end of group
        
        # Place one # right after the last letter of this first group
        if last_letter_col >= 0 and last_letter_col + 1 < cols:
            if new_grid[row][last_letter_col + 1] == "":
                new_grid[row][last_letter_col + 1] = "#"
    
    elif direction == "vertical" and target_col is not None and 0 <= target_col < cols:
        col = target_col
        in_group = False
        last_letter_row = -1
        for r in range(rows):
            cell = new_grid[r][col]
            if cell == "#":
                if in_group:
                    break
                continue
            if cell != "":
                in_group = True
                last_letter_row = r
            else:
                if in_group:
                    break
        
        if last_letter_row >= 0 and last_letter_row + 1 < rows:
            if new_grid[last_letter_row + 1][col] == "":
                new_grid[last_letter_row + 1][col] = "#"
    
    return new_grid

def find_word_positions_on_target(grid: List[List[str]], direction: str, target_row: int = None, target_col: int = None, allow_empty: bool = False) -> List[Dict[str, Any]]:
    """Find positions on a specific row (horizontal) or column (vertical).
    If target is None, search all rows/columns.
    If allow_empty is True, also return positions on fully empty rows/cols (for priority words)."""
    rows = len(grid)
    cols = len(grid[0])
    positions = []
    
    if direction == "horizontal":
        row_range = [target_row] if target_row is not None else range(rows)
        for row in row_range:
            if row < 0 or row >= rows:
                continue
            for col in range(cols):
                if col == 0 or grid[row][col - 1] == "#":
                    pattern = []
                    end_col = col
                    while end_col < cols and grid[row][end_col] != "#":
                        pattern.append(grid[row][end_col])
                        end_col += 1
                    
                    if len(pattern) >= 2:
                        has_letter = any(c != "" for c in pattern)
                        has_empty = any(c == "" for c in pattern)
                        if (has_letter and has_empty) or (allow_empty and has_empty):
                            positions.append({
                                "row": row,
                                "col": col,
                                "pattern": pattern,
                                "max_length": len(pattern)
                            })
    else:  # vertical
        col_range = [target_col] if target_col is not None else range(cols)
        for col in col_range:
            if col < 0 or col >= cols:
                continue
            for row in range(rows):
                if row == 0 or grid[row - 1][col] == "#":
                    pattern = []
                    end_row = row
                    while end_row < rows and grid[end_row][col] != "#":
                        pattern.append(grid[end_row][col])
                        end_row += 1
                    
                    if len(pattern) >= 2:
                        has_letter = any(c != "" for c in pattern)
                        has_empty = any(c == "" for c in pattern)
                        if (has_letter and has_empty) or (allow_empty and has_empty):
                            positions.append({
                                "row": row,
                                "col": col,
                                "pattern": pattern,
                                "max_length": len(pattern)
                            })
    
    return positions

def get_next_target(words_placed: List[Dict[str, Any]], direction: str, grid_rows: int, grid_cols: int):
    """Determine the next target row/col based on last placed words.
    - Horizontal: next row below the last horizontal word placed
    - Vertical: next column to the right of the last vertical word placed
    If none placed in that direction yet, use the first/init word position.
    """
    if not words_placed:
        return {"target_row": None, "target_col": None}
    
    if direction == "horizontal":
        # Find the last HORIZONTAL word placed, to get the next row
        last_h_row = -1
        for wp in words_placed:
            if wp.get("direction") == "horizontal":
                last_h_row = max(last_h_row, wp.get("row", 0))
        
        if last_h_row >= 0:
            # Target = next row after the last horizontal word
            target_row = last_h_row + 1
        else:
            # No horizontal word placed yet (shouldn't happen after init),
            # use the row below the first word
            target_row = words_placed[0].get("row", 0) + 1
        
        if target_row >= grid_rows:
            target_row = None
        return {"target_row": target_row, "target_col": None}
    
    else:  # vertical
        # Find the last VERTICAL word placed, to get the next column
        last_v_col = -1
        for wp in words_placed:
            if wp.get("direction") == "vertical":
                last_v_col = max(last_v_col, wp.get("col", 0))
        
        if last_v_col >= 0:
            # Target = next column after the last vertical word
            target_col = last_v_col + 1
        else:
            # No vertical word placed yet, use the column after the first word
            target_col = words_placed[0].get("col", 0) + 1
        
        if target_col >= grid_cols:
            target_col = None
        return {"target_row": None, "target_col": target_col}

def word_matches_pattern(word: str, pattern: List[str]) -> bool:
    """Check if a word matches a pattern.
    - Letters in pattern must match word letters at that position.
    - Empty cells accept any letter.
    - The cell right AFTER the word must NOT be an existing letter 
      (must be empty, '#', or end of pattern) to avoid touching another word."""
    if len(word) > len(pattern):
        return False
    
    for i, letter in enumerate(word):
        if pattern[i] != "" and pattern[i] != letter:
            return False
    
    # Check that the cell right after the word is not a letter
    # (it must be empty, '#', or the word fills the entire pattern)
    if len(word) < len(pattern):
        next_cell = pattern[len(word)]
        if next_cell != "" and next_cell != "#":
            # There's an existing letter right after the word end — not allowed
            return False
    
    return True

def find_matching_words(pattern: List[str], words_list: List[str], excluded: List[str], max_results: int = 50) -> List[str]:
    """Find words that match the pattern, prioritizing words that fill the full pattern length.
    words_list is already sorted by length (longest first)."""
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
    
    # Sort: prioritize words that fill the full pattern, then by length descending
    matching.sort(key=lambda w: (-1 if len(w) == max_len else 0, -len(w)))
    return matching

def get_word_list(session_id: Optional[str]) -> List[str]:
    """Get the main word list (always the built-in dictionary)"""
    return WORDS_BY_LENGTH

def get_priority_list(session_id: Optional[str]) -> List[str]:
    """Get the priority word list for a session (uploaded by user)"""
    if session_id and session_id in priority_word_lists:
        return priority_word_lists[session_id]
    return []

def get_priority_original(session_id: Optional[str], normalized: str) -> str:
    """Get original form of a priority word"""
    if session_id and session_id in priority_word_originals:
        return priority_word_originals[session_id].get(normalized, get_original_word(normalized))
    return get_original_word(normalized)

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
    
    # Validate cross directions after init
    words_list = get_word_list(config.session_id)
    grid = validate_cross_direction(grid, "horizontal", words_list)
    grid = validate_cross_direction(grid, "vertical", words_list)
    
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
    """Propose a new word based on existing letters, targeting the next row/col"""
    
    grid = request.grid_state.get("grid", [])
    direction = request.direction
    words_placed = request.grid_state.get("words_placed", [])
    grid_rows = len(grid)
    grid_cols = len(grid[0]) if grid else 0
    
    if not grid:
        raise HTTPException(status_code=400, detail="Grille invalide")
    
    # Determine target row/col based on last placed word
    target = get_next_target(words_placed, direction, grid_rows, grid_cols)
    target_row = target.get("target_row")
    target_col = target.get("target_col")
    
    # Check if we have priority words
    priority_list = get_priority_list(request.session_id)
    has_priority = len(priority_list) > 0
    
    # Search positions with letter constraints (for dictionary words)
    positions = find_word_positions_on_target(grid, direction, target_row, target_col)
    actual_target_row = target_row
    actual_target_col = target_col
    
    # Fallback for constrained positions
    if not positions and (target_row is not None or target_col is not None):
        if direction == "horizontal" and target_row is not None:
            for offset in range(1, grid_rows):
                for try_row in [target_row + offset, target_row - offset]:
                    if 0 <= try_row < grid_rows:
                        positions = find_word_positions_on_target(grid, direction, try_row, None)
                        if positions:
                            actual_target_row = try_row
                            break
                if positions:
                    break
        elif direction == "vertical" and target_col is not None:
            for offset in range(1, grid_cols):
                for try_col in [target_col + offset, target_col - offset]:
                    if 0 <= try_col < grid_cols:
                        positions = find_word_positions_on_target(grid, direction, None, try_col)
                        if positions:
                            actual_target_col = try_col
                            break
                if positions:
                    break
    
    # For priority words: also collect ALL positions including empty rows/cols
    all_empty_positions = []
    if has_priority:
        all_empty_positions = find_word_positions_on_target(grid, direction, None, None, allow_empty=True)
    
    if not positions and not all_empty_positions:
        new_grid = fill_black_after_letters(grid, direction, target_row, target_col)
        return {
            "proposal": None,
            "grid": new_grid,
            "message": f"Aucune position disponible pour un mot {direction}. Cases noires ajoutées."
        }
    
    # Get word list
    words_list = get_word_list(request.session_id)
    
    # Get already placed words
    placed_word_names = [w.get("word", "") for w in words_placed]
    
    all_proposals = []
    priority_proposals = []
    
    # 1) Search priority words on ALL positions (including empty rows/cols)
    if has_priority and all_empty_positions:
        for pos in all_empty_positions:
            matching_prio = find_matching_words(pos["pattern"], priority_list, placed_word_names, max_results=20)
            for word in matching_prio:
                if word not in placed_word_names and not any(p["word"] == word for p in priority_proposals):
                    entry = {
                        "word": word,
                        "original_word": get_priority_original(request.session_id, word),
                        "direction": direction,
                        "row": pos["row"],
                        "col": pos["col"],
                        "length": len(word),
                        "is_priority": True
                    }
                    priority_proposals.append(entry)
                    all_proposals.append(entry)
    
    # 2) Search main dictionary on constrained positions only
    for pos in positions:
        matching = find_matching_words(pos["pattern"], words_list, placed_word_names, max_results=20)
        for word in matching:
            if word not in placed_word_names and not any(p["word"] == word for p in all_proposals):
                is_priority = word in priority_list
                entry = {
                    "word": word,
                    "original_word": get_priority_original(request.session_id, word) if is_priority else get_original_word(word),
                    "direction": direction,
                    "row": pos["row"],
                    "col": pos["col"],
                    "length": len(word),
                    "is_priority": is_priority
                }
                all_proposals.append(entry)
                if is_priority:
                    priority_proposals.append(entry)
    
    if not all_proposals:
        # No matching word found: fill black cells on the actual row/col searched
        new_grid = fill_black_after_letters(grid, direction, actual_target_row, actual_target_col)
        return {
            "proposal": None,
            "grid": new_grid,
            "message": f"Aucun mot trouvé pour la direction {direction}. Cases noires ajoutées."
        }
    
    # Priority: pick from priority list first (longest priority word), else longest overall
    if priority_proposals:
        priority_proposals.sort(key=lambda x: -x["length"])
        proposal = priority_proposals[0]
    else:
        all_proposals.sort(key=lambda x: -x["length"])
        proposal = all_proposals[0]
    
    return {
        "proposal": proposal,
        "message": f"Mot proposé: {proposal['original_word']}"
    }

@api_router.post("/crossword/reject")
async def reject_and_propose(request: RejectWordRequest):
    """Reject current word and propose a new one on the same target row/col"""
    
    grid = request.grid_state.get("grid", [])
    direction = request.direction
    rejected = [normalize_word(w) for w in request.rejected_words]
    words_placed = request.grid_state.get("words_placed", [])
    grid_rows = len(grid)
    grid_cols = len(grid[0]) if grid else 0
    
    if not grid:
        raise HTTPException(status_code=400, detail="Grille invalide")
    
    # Determine target row/col based on last placed word
    target = get_next_target(words_placed, direction, grid_rows, grid_cols)
    target_row = target.get("target_row")
    target_col = target.get("target_col")
    
    # Check if we have priority words
    priority_list = get_priority_list(request.session_id)
    has_priority = len(priority_list) > 0
    
    # Search constrained positions
    positions = find_word_positions_on_target(grid, direction, target_row, target_col)
    actual_target_row = target_row
    actual_target_col = target_col
    
    if not positions and (target_row is not None or target_col is not None):
        if direction == "horizontal" and target_row is not None:
            for offset in range(1, grid_rows):
                for try_row in [target_row + offset, target_row - offset]:
                    if 0 <= try_row < grid_rows:
                        positions = find_word_positions_on_target(grid, direction, try_row, None)
                        if positions:
                            actual_target_row = try_row
                            break
                if positions:
                    break
        elif direction == "vertical" and target_col is not None:
            for offset in range(1, grid_cols):
                for try_col in [target_col + offset, target_col - offset]:
                    if 0 <= try_col < grid_cols:
                        positions = find_word_positions_on_target(grid, direction, None, try_col)
                        if positions:
                            actual_target_col = try_col
                            break
                if positions:
                    break
    
    # For priority words: collect ALL positions including empty
    all_empty_positions = []
    if has_priority:
        all_empty_positions = find_word_positions_on_target(grid, direction, None, None, allow_empty=True)
    
    if not positions and not all_empty_positions:
        new_grid = fill_black_after_letters(grid, direction, target_row, target_col)
        return {
            "proposal": None,
            "grid": new_grid,
            "message": f"Aucune position disponible pour un mot {direction}. Cases noires ajoutées."
        }
    
    # Get word list
    words_list = get_word_list(request.session_id)
    
    # Get already placed words + rejected words
    placed_word_names = [w.get("word", "") for w in words_placed]
    excluded = placed_word_names + rejected
    
    all_proposals = []
    priority_proposals = []
    
    # 1) Search priority words on ALL positions
    if has_priority and all_empty_positions:
        for pos in all_empty_positions:
            matching_prio = find_matching_words(pos["pattern"], priority_list, excluded, max_results=30)
            for word in matching_prio:
                if word not in excluded and not any(p["word"] == word for p in priority_proposals):
                    entry = {
                        "word": word,
                        "original_word": get_priority_original(request.session_id, word),
                        "direction": direction,
                        "row": pos["row"],
                        "col": pos["col"],
                        "length": len(word),
                        "is_priority": True
                    }
                    priority_proposals.append(entry)
                    all_proposals.append(entry)
    
    # 2) Search main dictionary on constrained positions
    for pos in positions:
        matching = find_matching_words(pos["pattern"], words_list, excluded, max_results=30)
        for word in matching:
            if not any(p["word"] == word for p in all_proposals):
                is_priority = word in priority_list
                entry = {
                    "word": word,
                    "original_word": get_priority_original(request.session_id, word) if is_priority else get_original_word(word),
                    "direction": direction,
                    "row": pos["row"],
                    "col": pos["col"],
                    "length": len(word),
                    "is_priority": is_priority
                }
                all_proposals.append(entry)
                if is_priority:
                    priority_proposals.append(entry)
    
    if not all_proposals:
        new_grid = fill_black_after_letters(grid, direction, actual_target_row, actual_target_col)
        return {
            "proposal": None,
            "grid": new_grid,
            "message": f"Plus de mots disponibles pour la direction {direction}. Cases noires ajoutées."
        }
    
    # Priority: pick from priority list first, else longest overall
    if priority_proposals:
        priority_proposals.sort(key=lambda x: -x["length"])
        proposal = priority_proposals[0]
    else:
        all_proposals.sort(key=lambda x: -x["length"])
        proposal = all_proposals[0]
    
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
    
    # Validate cross direction: check perpendicular groups of 3+ letters
    words_list = get_word_list(request.grid_state.get("session_id"))
    new_grid = validate_cross_direction(new_grid, request.direction, words_list)
    
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

class FinishGridRequest(BaseModel):
    grid_state: Dict[str, Any]

@api_router.post("/crossword/finish")
async def finish_grid(request: FinishGridRequest):
    """Fill all empty cells with black cells to finish the grid"""
    grid = request.grid_state.get("grid", [])
    if not grid:
        raise HTTPException(status_code=400, detail="Grille invalide")
    
    new_grid = [[("#" if cell == "" else cell) for cell in row] for row in grid]
    
    return {
        "grid": new_grid,
        "message": "Grille terminée — toutes les cases vides sont noires"
    }

@api_router.post("/words/upload")
async def upload_word_list(file: UploadFile = File(...)):
    """Upload a priority word list to place in the grid first"""
    
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Le fichier doit être un fichier .txt")
    
    try:
        content = await file.read()
        text = content.decode('utf-8')
        
        # Parse words (one per line)
        words_normalized = []
        originals = {}
        for line in text.split('\n'):
            word = line.strip()
            if word and len(word) >= 2:
                normalized = normalize_word(word)
                if normalized.isalpha() and normalized not in originals:
                    words_normalized.append(normalized)
                    originals[normalized] = word  # keep original with accents
        
        if len(words_normalized) < 1:
            raise HTTPException(status_code=400, detail="Le fichier doit contenir au moins 1 mot valide")
        
        # Sort by length (longest first)
        words_normalized.sort(key=lambda x: -len(x))
        
        # Generate session ID
        session_id = str(uuid.uuid4())
        priority_word_lists[session_id] = words_normalized
        priority_word_originals[session_id] = originals
        
        return {
            "session_id": session_id,
            "word_count": len(words_normalized),
            "words": [originals[w] for w in words_normalized],
            "message": f"{len(words_normalized)} mots prioritaires chargés"
        }
        
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Erreur de décodage du fichier. Utilisez l'encodage UTF-8.")

@api_router.get("/words/count")
async def get_word_count(session_id: Optional[str] = None):
    """Get the count of words in the dictionary and priority list"""
    words_list = get_word_list(session_id)
    priority_list = get_priority_list(session_id)
    return {
        "count": len(words_list),
        "priority_count": len(priority_list),
        "has_priority": len(priority_list) > 0
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
