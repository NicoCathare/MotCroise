from fastapi import FastAPI, APIRouter, UploadFile, File, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
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

app = FastAPI()
api_router = APIRouter(prefix="/api")

# In-memory storage for priority word lists per session
priority_word_lists: Dict[str, List[str]] = {}
priority_word_originals: Dict[str, Dict[str, str]] = {}

# ── Models ────────────────────────────────────────────────────────────────────

class GridConfig(BaseModel):
    rows: int = Field(ge=5, le=20)
    cols: int = Field(ge=5, le=20)
    first_horizontal_word: str
    first_vertical_word: str
    session_id: Optional[str] = None

class ProposeWordRequest(BaseModel):
    grid_state: Dict[str, Any]
    direction: str
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

class FinishGridRequest(BaseModel):
    grid_state: Dict[str, Any]

# ── Cell helpers ──────────────────────────────────────────────────────────────

def _is_empty(cell: str) -> bool:
    return cell == ""

def _is_blocked(cell: str) -> bool:
    return cell == "#"

def _is_letter(cell: str) -> bool:
    return cell != "" and cell != "#"

# ── Grid primitives ──────────────────────────────────────────────────────────

def create_empty_grid(rows: int, cols: int) -> List[List[str]]:
    return [["" for _ in range(cols)] for _ in range(rows)]

def can_place_word(grid: List[List[str]], word: str, row: int, col: int, direction: str) -> bool:
    rows, cols = len(grid), len(grid[0])
    if direction == "horizontal":
        if col + len(word) > cols:
            return False
        return all(
            not _is_blocked(grid[row][col + i]) and (_is_empty(grid[row][col + i]) or grid[row][col + i] == ch)
            for i, ch in enumerate(word)
        )
    else:
        if row + len(word) > rows:
            return False
        return all(
            not _is_blocked(grid[row + i][col]) and (_is_empty(grid[row + i][col]) or grid[row + i][col] == ch)
            for i, ch in enumerate(word)
        )

def _set_black_if_empty(grid: List[List[str]], r: int, c: int, rows: int, cols: int):
    if 0 <= r < rows and 0 <= c < cols and _is_empty(grid[r][c]):
        grid[r][c] = "#"

def place_word(grid: List[List[str]], word: str, row: int, col: int, direction: str) -> List[List[str]]:
    new_grid = [r[:] for r in grid]
    rows, cols = len(grid), len(grid[0])
    if direction == "horizontal":
        for i, ch in enumerate(word):
            new_grid[row][col + i] = ch
        _set_black_if_empty(new_grid, row, col + len(word), rows, cols)
        _set_black_if_empty(new_grid, row, col - 1, rows, cols)
    else:
        for i, ch in enumerate(word):
            new_grid[row + i][col] = ch
        _set_black_if_empty(new_grid, row + len(word), col, rows, cols)
        _set_black_if_empty(new_grid, row - 1, col, rows, cols)
    return new_grid

# ── Cross-direction validation ────────────────────────────────────────────────

def _find_letter_groups(grid, direction, index, size):
    """Find groups of 3+ consecutive letters along a line."""
    groups, start = [], None
    for pos in range(size):
        cell = grid[pos][index] if direction == "col" else grid[index][pos]
        if _is_letter(cell):
            if start is None:
                start = pos
        else:
            if start is not None and pos - start >= 3:
                groups.append((start, pos - start))
            start = None
    if start is not None and size - start >= 3:
        groups.append((start, size - start))
    return groups

def _pattern_has_valid_word(pattern: List[str], words_list: List[str]) -> bool:
    pat_len = len(pattern)
    for word in words_list:
        if len(word) != pat_len:
            continue
        if all(word[i] == pattern[i] for i in range(pat_len)):
            return True
    return False

def validate_cross_direction(grid: List[List[str]], placed_direction: str, words_list: List[str]) -> List[List[str]]:
    new_grid = [r[:] for r in grid]
    rows, cols = len(grid), len(grid[0])

    if placed_direction == "horizontal":
        for col in range(cols):
            for start, length in _find_letter_groups(new_grid, "col", col, rows):
                pattern = [new_grid[start + i][col] for i in range(length)]
                if not _pattern_has_valid_word(pattern, words_list):
                    _set_black_if_empty(new_grid, start - 1, col, rows, cols)
                    _set_black_if_empty(new_grid, start + length, col, rows, cols)
    else:
        for row in range(rows):
            for start, length in _find_letter_groups(new_grid, "row", row, cols):
                pattern = [new_grid[row][start + i] for i in range(length)]
                if not _pattern_has_valid_word(pattern, words_list):
                    _set_black_if_empty(new_grid, row, start - 1, rows, cols)
                    _set_black_if_empty(new_grid, row, start + length, rows, cols)
    return new_grid

# ── Fill black after letters ──────────────────────────────────────────────────

def _find_first_letter_group_end(grid_line: List[str]) -> int:
    """Return the index of the last letter in the first consecutive letter group, or -1."""
    in_group = False
    last = -1
    for i, cell in enumerate(grid_line):
        if _is_blocked(cell):
            if in_group:
                break
            continue
        if _is_letter(cell):
            in_group = True
            last = i
        elif in_group:
            break
    return last

def fill_black_after_letters(grid: List[List[str]], direction: str, target_row=None, target_col=None) -> List[List[str]]:
    new_grid = [r[:] for r in grid]
    rows, cols = len(grid), len(grid[0])

    if direction == "horizontal" and target_row is not None and 0 <= target_row < rows:
        last = _find_first_letter_group_end(new_grid[target_row])
        if last >= 0:
            _set_black_if_empty(new_grid, target_row, last + 1, rows, cols)

    elif direction == "vertical" and target_col is not None and 0 <= target_col < cols:
        col_line = [new_grid[r][target_col] for r in range(rows)]
        last = _find_first_letter_group_end(col_line)
        if last >= 0:
            _set_black_if_empty(new_grid, last + 1, target_col, rows, cols)

    return new_grid

# ── Position finding ──────────────────────────────────────────────────────────

def _extract_pattern(grid, direction, row, col, rows, cols):
    """Extract a pattern (list of cell values) starting at (row,col) until a '#' or edge."""
    pattern = []
    if direction == "horizontal":
        c = col
        while c < cols and not _is_blocked(grid[row][c]):
            pattern.append(grid[row][c])
            c += 1
    else:
        r = row
        while r < rows and not _is_blocked(grid[r][col]):
            pattern.append(grid[r][col])
            r += 1
    return pattern

def find_word_positions_on_target(grid, direction, target_row=None, target_col=None, allow_empty=False):
    rows, cols = len(grid), len(grid[0])
    positions = []

    if direction == "horizontal":
        row_range = [target_row] if target_row is not None else range(rows)
        for row in row_range:
            if row < 0 or row >= rows:
                continue
            for col in range(cols):
                if col == 0 or _is_blocked(grid[row][col - 1]):
                    pattern = _extract_pattern(grid, "horizontal", row, col, rows, cols)
                    if len(pattern) >= 2:
                        has_letter = any(_is_letter(c) for c in pattern)
                        has_empty = any(_is_empty(c) for c in pattern)
                        if (has_letter and has_empty) or (allow_empty and has_empty):
                            positions.append({"row": row, "col": col, "pattern": pattern, "max_length": len(pattern)})
    else:
        col_range = [target_col] if target_col is not None else range(cols)
        for col in col_range:
            if col < 0 or col >= cols:
                continue
            for row in range(rows):
                if row == 0 or _is_blocked(grid[row - 1][col]):
                    pattern = _extract_pattern(grid, "vertical", row, col, rows, cols)
                    if len(pattern) >= 2:
                        has_letter = any(_is_letter(c) for c in pattern)
                        has_empty = any(_is_empty(c) for c in pattern)
                        if (has_letter and has_empty) or (allow_empty and has_empty):
                            positions.append({"row": row, "col": col, "pattern": pattern, "max_length": len(pattern)})
    return positions

# ── Word matching ─────────────────────────────────────────────────────────────

def get_next_target(words_placed, direction, grid_rows, grid_cols):
    if not words_placed:
        return {"target_row": None, "target_col": None}
    if direction == "horizontal":
        last_h_row = max((wp.get("row", 0) for wp in words_placed if wp.get("direction") == "horizontal"), default=-1)
        target = (last_h_row + 1) if last_h_row >= 0 else (words_placed[0].get("row", 0) + 1)
        return {"target_row": target if target < grid_rows else None, "target_col": None}
    else:
        last_v_col = max((wp.get("col", 0) for wp in words_placed if wp.get("direction") == "vertical"), default=-1)
        target = (last_v_col + 1) if last_v_col >= 0 else (words_placed[0].get("col", 0) + 1)
        return {"target_row": None, "target_col": target if target < grid_cols else None}

def word_matches_pattern(word: str, pattern: List[str]) -> bool:
    if len(word) > len(pattern):
        return False
    for i, ch in enumerate(word):
        if not _is_empty(pattern[i]) and pattern[i] != ch:
            return False
    if len(word) < len(pattern):
        nxt = pattern[len(word)]
        if _is_letter(nxt):
            return False
    return True

def find_matching_words(pattern, words_list, excluded, max_results=50):
    matching = []
    max_len = len(pattern)
    for word in words_list:
        if len(word) > max_len or len(word) < 2 or word in excluded:
            continue
        if word_matches_pattern(word, pattern):
            matching.append(word)
            if len(matching) >= max_results:
                break
    matching.sort(key=lambda w: (-1 if len(w) == max_len else 0, -len(w)))
    return matching

# ── Word list helpers ─────────────────────────────────────────────────────────

def get_word_list(session_id=None):
    return WORDS_BY_LENGTH

def get_priority_list(session_id=None):
    if session_id and session_id in priority_word_lists:
        return priority_word_lists[session_id]
    return []

def get_priority_original(session_id, normalized):
    if session_id and session_id in priority_word_originals:
        return priority_word_originals[session_id].get(normalized, get_original_word(normalized))
    return get_original_word(normalized)

# ── Proposal helpers ──────────────────────────────────────────────────────────

def _fallback_positions(grid, direction, target_row, target_col, grid_rows, grid_cols):
    """Search nearby rows/cols for constrained positions."""
    positions = []
    actual_row, actual_col = target_row, target_col
    if direction == "horizontal" and target_row is not None:
        for offset in range(1, grid_rows):
            for try_row in [target_row + offset, target_row - offset]:
                if 0 <= try_row < grid_rows:
                    positions = find_word_positions_on_target(grid, direction, try_row, None)
                    if positions:
                        return positions, try_row, actual_col
    elif direction == "vertical" and target_col is not None:
        for offset in range(1, grid_cols):
            for try_col in [target_col + offset, target_col - offset]:
                if 0 <= try_col < grid_cols:
                    positions = find_word_positions_on_target(grid, direction, None, try_col)
                    if positions:
                        return positions, actual_row, try_col
    return positions, actual_row, actual_col

def _build_proposal_entry(word, direction, pos, is_priority, session_id):
    return {
        "word": word,
        "original_word": get_priority_original(session_id, word) if is_priority else get_original_word(word),
        "direction": direction,
        "row": pos["row"],
        "col": pos["col"],
        "length": len(word),
        "is_priority": is_priority,
    }

def _search_proposals(positions, words_list, priority_list, excluded, direction, session_id, all_empty_positions=None):
    """Search for word proposals. Returns (all_proposals, priority_proposals)."""
    all_proposals = []
    priority_proposals = []
    seen_words = set()

    # 1) Priority words on ALL positions (including empty)
    if priority_list and all_empty_positions:
        for pos in all_empty_positions:
            for word in find_matching_words(pos["pattern"], priority_list, excluded, max_results=20):
                if word not in excluded and word not in seen_words:
                    seen_words.add(word)
                    entry = _build_proposal_entry(word, direction, pos, True, session_id)
                    priority_proposals.append(entry)
                    all_proposals.append(entry)

    # 2) Main dictionary on constrained positions
    for pos in positions:
        for word in find_matching_words(pos["pattern"], words_list, excluded, max_results=20):
            if word not in seen_words:
                seen_words.add(word)
                is_prio = word in priority_list if priority_list else False
                entry = _build_proposal_entry(word, direction, pos, is_prio, session_id)
                all_proposals.append(entry)
                if is_prio:
                    priority_proposals.append(entry)

    return all_proposals, priority_proposals

def _pick_best_proposal(all_proposals, priority_proposals):
    if priority_proposals:
        priority_proposals.sort(key=lambda x: -x["length"])
        return priority_proposals[0]
    all_proposals.sort(key=lambda x: -x["length"])
    return all_proposals[0]

# ── API Routes ────────────────────────────────────────────────────────────────

@api_router.get("/")
async def root():
    return {"message": "Générateur de Mots Croisés API"}

@api_router.post("/crossword/init")
async def init_crossword(config: GridConfig):
    h_word = normalize_word(config.first_horizontal_word.strip())
    v_word = normalize_word(config.first_vertical_word.strip())

    if len(h_word) < 2 or len(v_word) < 2:
        raise HTTPException(status_code=400, detail="Les mots doivent avoir au moins 2 lettres")
    if len(h_word) > config.cols:
        raise HTTPException(status_code=400, detail=f"Le mot horizontal est trop long pour {config.cols} colonnes")
    if len(v_word) > config.rows:
        raise HTTPException(status_code=400, detail=f"Le mot vertical est trop long pour {config.rows} lignes")

    intersection = None
    for i, hc in enumerate(h_word):
        for j, vc in enumerate(v_word):
            if hc == vc:
                intersection = (i, j)
                break
        if intersection:
            break
    if not intersection:
        raise HTTPException(status_code=400, detail="Les mots doivent avoir au moins une lettre en commun pour se croiser")

    h_pos, v_pos = intersection
    h_row, h_col = v_pos, 0
    if h_col + len(h_word) > config.cols:
        h_col = config.cols - len(h_word)
    v_row, v_col = 0, h_col + h_pos

    grid = create_empty_grid(config.rows, config.cols)
    grid = place_word(grid, h_word, h_row, h_col, "horizontal")
    grid = place_word(grid, v_word, v_row, v_col, "vertical")

    words_list = get_word_list(config.session_id)
    grid = validate_cross_direction(grid, "horizontal", words_list)
    grid = validate_cross_direction(grid, "vertical", words_list)

    words_placed = [
        {"word": h_word, "original": get_original_word(h_word), "direction": "horizontal", "row": h_row, "col": h_col},
        {"word": v_word, "original": get_original_word(v_word), "direction": "vertical", "row": v_row, "col": v_col},
    ]
    return {"grid": grid, "rows": config.rows, "cols": config.cols, "words_placed": words_placed, "message": "Grille initialisée avec succès"}

@api_router.post("/crossword/propose")
async def propose_word(request: ProposeWordRequest):
    grid = request.grid_state.get("grid", [])
    direction = request.direction
    words_placed = request.grid_state.get("words_placed", [])
    if not grid:
        raise HTTPException(status_code=400, detail="Grille invalide")

    grid_rows, grid_cols = len(grid), len(grid[0])
    target = get_next_target(words_placed, direction, grid_rows, grid_cols)
    target_row, target_col = target["target_row"], target["target_col"]

    priority_list = get_priority_list(request.session_id)
    positions = find_word_positions_on_target(grid, direction, target_row, target_col)
    actual_target_row, actual_target_col = target_row, target_col

    if not positions and (target_row is not None or target_col is not None):
        positions, actual_target_row, actual_target_col = _fallback_positions(grid, direction, target_row, target_col, grid_rows, grid_cols)

    all_empty_positions = find_word_positions_on_target(grid, direction, None, None, allow_empty=True) if priority_list else []

    if not positions and not all_empty_positions:
        return {"proposal": None, "grid": fill_black_after_letters(grid, direction, target_row, target_col),
                "message": f"Aucune position disponible pour un mot {direction}. Cases noires ajoutées."}

    placed_names = [w.get("word", "") for w in words_placed]
    all_proposals, priority_proposals = _search_proposals(
        positions, get_word_list(request.session_id), priority_list, placed_names, direction, request.session_id, all_empty_positions)

    if not all_proposals:
        return {"proposal": None, "grid": fill_black_after_letters(grid, direction, actual_target_row, actual_target_col),
                "message": f"Aucun mot trouvé pour la direction {direction}. Cases noires ajoutées."}

    proposal = _pick_best_proposal(all_proposals, priority_proposals)
    return {"proposal": proposal, "message": f"Mot proposé: {proposal['original_word']}"}

@api_router.post("/crossword/reject")
async def reject_and_propose(request: RejectWordRequest):
    grid = request.grid_state.get("grid", [])
    direction = request.direction
    rejected = [normalize_word(w) for w in request.rejected_words]
    words_placed = request.grid_state.get("words_placed", [])
    if not grid:
        raise HTTPException(status_code=400, detail="Grille invalide")

    grid_rows, grid_cols = len(grid), len(grid[0])
    target = get_next_target(words_placed, direction, grid_rows, grid_cols)
    target_row, target_col = target["target_row"], target["target_col"]

    priority_list = get_priority_list(request.session_id)
    positions = find_word_positions_on_target(grid, direction, target_row, target_col)
    actual_target_row, actual_target_col = target_row, target_col

    if not positions and (target_row is not None or target_col is not None):
        positions, actual_target_row, actual_target_col = _fallback_positions(grid, direction, target_row, target_col, grid_rows, grid_cols)

    all_empty_positions = find_word_positions_on_target(grid, direction, None, None, allow_empty=True) if priority_list else []

    if not positions and not all_empty_positions:
        return {"proposal": None, "grid": fill_black_after_letters(grid, direction, target_row, target_col),
                "message": f"Aucune position disponible pour un mot {direction}. Cases noires ajoutées."}

    excluded = [w.get("word", "") for w in words_placed] + rejected
    all_proposals, priority_proposals = _search_proposals(
        positions, get_word_list(request.session_id), priority_list, excluded, direction, request.session_id, all_empty_positions)

    if not all_proposals:
        return {"proposal": None, "grid": fill_black_after_letters(grid, direction, actual_target_row, actual_target_col),
                "message": f"Plus de mots disponibles pour la direction {direction}. Cases noires ajoutées."}

    proposal = _pick_best_proposal(all_proposals, priority_proposals)
    return {"proposal": proposal, "message": f"Nouveau mot proposé: {proposal['original_word']}"}

@api_router.post("/crossword/place")
async def place_word_on_grid(request: PlaceWordRequest):
    grid = request.grid_state.get("grid", [])
    word = normalize_word(request.word)
    if not grid:
        raise HTTPException(status_code=400, detail="Grille invalide")
    if not can_place_word(grid, word, request.row, request.col, request.direction):
        raise HTTPException(status_code=400, detail="Le mot ne peut pas être placé à cette position")

    new_grid = place_word(grid, word, request.row, request.col, request.direction)
    new_grid = validate_cross_direction(new_grid, request.direction, get_word_list(request.grid_state.get("session_id")))

    words_placed = request.grid_state.get("words_placed", [])
    words_placed.append({"word": word, "original": get_original_word(word), "direction": request.direction, "row": request.row, "col": request.col})
    return {"grid": new_grid, "words_placed": words_placed, "message": f"Mot '{get_original_word(word)}' placé avec succès"}

@api_router.post("/crossword/finish")
async def finish_grid(request: FinishGridRequest):
    grid = request.grid_state.get("grid", [])
    if not grid:
        raise HTTPException(status_code=400, detail="Grille invalide")
    return {"grid": [["#" if _is_empty(cell) else cell for cell in row] for row in grid],
            "message": "Grille terminée — toutes les cases vides sont noires"}

@api_router.post("/words/upload")
async def upload_word_list(file: UploadFile = File(...)):
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Le fichier doit être un fichier .txt")
    try:
        text = (await file.read()).decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Erreur de décodage du fichier. Utilisez l'encodage UTF-8.")

    words_normalized, originals = [], {}
    for line in text.split('\n'):
        word = line.strip()
        if word and len(word) >= 2:
            normalized = normalize_word(word)
            if normalized.isalpha() and normalized not in originals:
                words_normalized.append(normalized)
                originals[normalized] = word
    if not words_normalized:
        raise HTTPException(status_code=400, detail="Le fichier doit contenir au moins 1 mot valide")

    words_normalized.sort(key=lambda x: -len(x))
    session_id = str(uuid.uuid4())
    priority_word_lists[session_id] = words_normalized
    priority_word_originals[session_id] = originals
    return {"session_id": session_id, "word_count": len(words_normalized),
            "words": [originals[w] for w in words_normalized],
            "message": f"{len(words_normalized)} mots prioritaires chargés"}

@api_router.get("/words/count")
async def get_word_count(session_id: Optional[str] = None):
    return {"count": len(get_word_list(session_id)), "priority_count": len(get_priority_list(session_id)),
            "has_priority": len(get_priority_list(session_id)) > 0}

# ── App setup ─────────────────────────────────────────────────────────────────

app.include_router(api_router)
app.add_middleware(CORSMiddleware, allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','), allow_methods=["*"], allow_headers=["*"])

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
