import { useState, useCallback, useEffect } from "react";
import "@/App.css";
import axios from "axios";
import { Upload, RefreshCw, Check, X, Grid3X3, ArrowRight, ArrowDown, Square, Undo2 } from "lucide-react";
import { Toaster, toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// ── Helpers ──────────────────────────────────────────────────────────────────

const buildHighlightCells = (proposal, direction) => {
  const cells = [];
  for (let i = 0; i < proposal.length; i++) {
    cells.push(
      direction === "horizontal"
        ? { row: proposal.row, col: proposal.col + i }
        : { row: proposal.row + i, col: proposal.col }
    );
  }
  return cells;
};

// ── useApi hook ──────────────────────────────────────────────────────────────

const useApi = (sessionId) => {
  const post = useCallback(async (path, data) => {
    const response = await axios.post(`${API}${path}`, data);
    return response.data;
  }, []);

  const postForm = useCallback(async (path, formData) => {
    const response = await axios.post(`${API}${path}`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  }, []);

  return { post, postForm, sessionId };
};

// ── ConfigPanel ──────────────────────────────────────────────────────────────

const ConfigPanel = ({ config, setConfig, onInit, isLoading, sessionId, onFileUpload, wordCount, priorityWords }) => {
  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (file) onFileUpload(file);
  };

  return (
    <div className="w-full md:w-80 border-r border-[#E5E5E5] bg-[#F9F9F9] p-6 flex flex-col gap-6 overflow-y-auto">
      <div>
        <h1 className="font-heading text-2xl font-bold tracking-tight text-[#0A0A0A]" data-testid="app-title">
          Générateur de Mots Croisés
        </h1>
        <p className="text-sm text-[#0A0A0A]/60 mt-2">Créez votre grille de mots croisés</p>
      </div>

      <div className="flex flex-col gap-4">
        <label className="label-swiss">Dimensions de la grille</label>
        <div className="flex gap-4">
          <div className="flex-1">
            <label className="text-xs text-[#0A0A0A]/60 mb-1 block">Lignes</label>
            <input type="number" min="5" max="20" value={config.rows}
              onChange={(e) => setConfig({ ...config, rows: parseInt(e.target.value) || 5 })}
              className="input-swiss w-full" data-testid="input-rows" />
          </div>
          <div className="flex-1">
            <label className="text-xs text-[#0A0A0A]/60 mb-1 block">Colonnes</label>
            <input type="number" min="5" max="20" value={config.cols}
              onChange={(e) => setConfig({ ...config, cols: parseInt(e.target.value) || 5 })}
              className="input-swiss w-full" data-testid="input-cols" />
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        <label className="label-swiss">Premiers mots</label>
        <div>
          <label className="text-xs text-[#0A0A0A]/60 mb-1 flex items-center gap-1"><ArrowRight size={12} /> Mot horizontal</label>
          <input type="text" value={config.firstHorizontal}
            onChange={(e) => setConfig({ ...config, firstHorizontal: e.target.value })}
            placeholder="ex: MAISON" className="input-swiss w-full uppercase" data-testid="input-horizontal" />
        </div>
        <div>
          <label className="text-xs text-[#0A0A0A]/60 mb-1 flex items-center gap-1"><ArrowDown size={12} /> Mot vertical</label>
          <input type="text" value={config.firstVertical}
            onChange={(e) => setConfig({ ...config, firstVertical: e.target.value })}
            placeholder="ex: ARBRE" className="input-swiss w-full uppercase" data-testid="input-vertical" />
        </div>
      </div>

      <button onClick={onInit} disabled={isLoading || !config.firstHorizontal || !config.firstVertical}
        className="btn-primary flex items-center justify-center gap-2" data-testid="btn-init">
        <Grid3X3 size={18} /> Créer la grille
      </button>

      <div className="border-t border-[#E5E5E5]" />

      <div className="flex flex-col gap-3">
        <label className="label-swiss">Mots prioritaires</label>
        <label className="upload-zone" data-testid="upload-zone">
          <Upload size={24} className="text-[#0A0A0A]/40" />
          <span className="text-sm text-[#0A0A0A]/60">
            {sessionId ? `${priorityWords.length} mots chargés` : "Charger un fichier .txt"}
          </span>
          <input type="file" accept=".txt" onChange={handleFileChange} className="hidden" data-testid="input-file" />
        </label>
        {priorityWords.length > 0 && (
          <div className="flex flex-col gap-1 max-h-32 overflow-y-auto">
            {priorityWords.map((w) => (
              <span key={`prio-${w}`} className="font-mono text-xs bg-white border border-[#E5E5E5] px-2 py-1">{w}</span>
            ))}
          </div>
        )}
        <p className="text-xs text-[#0A0A0A]/40">{wordCount} mots dans le dictionnaire</p>
      </div>
    </div>
  );
};

// ── CrosswordGrid ────────────────────────────────────────────────────────────

const CrosswordGrid = ({ grid, rows, cols, highlightedCells }) => {
  if (!grid || grid.length === 0) {
    return (
      <div className="flex-1 flex flex-col bg-white p-8 overflow-y-auto items-center justify-center">
        <div className="text-center">
          <Grid3X3 size={64} className="text-[#0A0A0A]/10 mx-auto mb-4" />
          <p className="text-[#0A0A0A]/40 text-lg">Configurez et créez votre grille</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-white p-8 overflow-y-auto items-center justify-center" data-testid="grid-container">
      <div className="crossword-grid"
        style={{ gridTemplateColumns: `repeat(${cols}, minmax(32px, 48px))`, gridTemplateRows: `repeat(${rows}, minmax(32px, 48px))` }}
        data-testid="crossword-grid">
        {grid.map((row, rowIdx) =>
          row.map((cell, colIdx) => {
            const isBlocked = cell === "#";
            const isEmpty = cell === "";
            const isHighlighted = highlightedCells?.some((h) => h.row === rowIdx && h.col === colIdx);
            return (
              <div key={`${rowIdx}-${colIdx}`}
                className={`crossword-cell ${isBlocked ? "blocked" : ""} ${isEmpty ? "empty" : ""} ${isHighlighted ? "active" : ""}`}
                data-testid={`cell-${rowIdx}-${colIdx}`}>
                {!isBlocked && cell}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

// ── ProposalPanel ────────────────────────────────────────────────────────────

const ProposalPanel = ({ proposal, onAccept, onReject, onRequestHorizontal, onRequestVertical, onFinish, onUndo, canUndo, isLoading, wordsPlaced, gridInitialized }) => (
  <div className="w-full md:w-96 border-l border-[#E5E5E5] bg-[#F9F9F9] p-6 flex flex-col gap-6 overflow-y-auto">
    <div>
      <h2 className="font-heading text-xl font-bold tracking-tight text-[#0A0A0A]">Propositions</h2>
      <p className="text-sm text-[#0A0A0A]/60 mt-1">Acceptez ou rejetez les mots proposés</p>
    </div>

    {gridInitialized && (
      <div className="flex flex-col gap-3">
        <button onClick={onRequestHorizontal} disabled={isLoading} className="btn-secondary flex items-center justify-center gap-2" data-testid="btn-request-horizontal">
          <ArrowRight size={16} /> Proposer mot horizontal
        </button>
        <button onClick={onRequestVertical} disabled={isLoading} className="btn-secondary flex items-center justify-center gap-2" data-testid="btn-request-vertical">
          <ArrowDown size={16} /> Proposer mot vertical
        </button>
        <button onClick={onFinish} disabled={isLoading} className="btn-primary flex items-center justify-center gap-2 bg-[#0A0A0A] hover:bg-[#333]" data-testid="btn-finish">
          <Square size={16} /> Terminer
        </button>
        <button onClick={onUndo} disabled={isLoading || !canUndo} className="btn-destructive flex items-center justify-center gap-2" data-testid="btn-undo">
          <Undo2 size={16} /> Annuler
        </button>
      </div>
    )}

    {proposal && (
      <ProposalCard proposal={proposal} onAccept={onAccept} onReject={onReject} isLoading={isLoading} />
    )}

    {isLoading && (
      <div className="flex items-center justify-center p-4">
        <RefreshCw size={24} className="animate-spin text-[#002FA7]" />
      </div>
    )}

    {wordsPlaced && wordsPlaced.length > 0 && (
      <WordsList wordsPlaced={wordsPlaced} />
    )}
  </div>
);

// ── ProposalCard ─────────────────────────────────────────────────────────────

const ProposalCard = ({ proposal, onAccept, onReject, isLoading }) => (
  <div className="proposal-card" data-testid="proposal-card">
    <div>
      <label className="label-swiss">Mot proposé</label>
      <p className="font-mono text-2xl font-bold mt-2 text-[#002FA7]" data-testid="proposed-word">{proposal.original_word}</p>
      {proposal.is_priority && (
        <span className="text-xs font-semibold text-[#008A00] uppercase tracking-wider mt-1 inline-block">Mot prioritaire</span>
      )}
    </div>
    <div className="flex gap-2 text-sm text-[#0A0A0A]/60">
      <span className="flex items-center gap-1">
        {proposal.direction === "horizontal" ? <ArrowRight size={14} /> : <ArrowDown size={14} />}
        {proposal.direction === "horizontal" ? "Horizontal" : "Vertical"}
      </span>
      <span>Ligne {proposal.row + 1}, Col {proposal.col + 1}</span>
    </div>
    <div className="flex gap-3 mt-2">
      <button onClick={onAccept} disabled={isLoading} className="btn-primary flex-1 flex items-center justify-center gap-2" data-testid="btn-accept">
        <Check size={16} /> Valider
      </button>
      <button onClick={onReject} disabled={isLoading} className="btn-destructive flex-1 flex items-center justify-center gap-2" data-testid="btn-reject">
        <X size={16} /> Rejeter
      </button>
    </div>
  </div>
);

// ── WordsList ────────────────────────────────────────────────────────────────

const WordsList = ({ wordsPlaced }) => (
  <div className="flex flex-col gap-3">
    <label className="label-swiss">Mots placés ({wordsPlaced.length})</label>
    <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
      {wordsPlaced.map((word, idx) => (
        <div key={`${word.word}-${word.row}-${word.col}`}
          className="flex items-center justify-between bg-white border border-[#E5E5E5] px-3 py-2"
          data-testid={`placed-word-${idx}`}>
          <span className="font-mono font-semibold">{word.original || word.word}</span>
          <span className="text-xs text-[#0A0A0A]/40 flex items-center gap-1">
            {word.direction === "horizontal" ? <ArrowRight size={12} /> : <ArrowDown size={12} />}
          </span>
        </div>
      ))}
    </div>
  </div>
);

// ── Main App ─────────────────────────────────────────────────────────────────

function App() {
  const [config, setConfig] = useState({ rows: 10, cols: 10, firstHorizontal: "", firstVertical: "" });
  const [gridState, setGridState] = useState({ grid: [], rows: 0, cols: 0, words_placed: [] });
  const [proposal, setProposal] = useState(null);
  const [rejectedWords, setRejectedWords] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [wordCount, setWordCount] = useState(0);
  const [highlightedCells, setHighlightedCells] = useState([]);
  const [history, setHistory] = useState([]);
  const [priorityWords, setPriorityWords] = useState([]);

  const { post, postForm } = useApi(sessionId);

  // Fetch word count on mount
  const fetchWordCount = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/words/count`, {
        params: sessionId ? { session_id: sessionId } : {},
      });
      setWordCount(response.data.count);
    } catch (_) { /* silently ignore */ }
  }, [sessionId]);

  useEffect(() => { fetchWordCount(); }, [fetchWordCount]);

  const saveToHistory = () => {
    setHistory((prev) => [...prev, JSON.parse(JSON.stringify(gridState))]);
  };

  const handleUndo = () => {
    if (history.length === 0) return;
    setGridState(history[history.length - 1]);
    setHistory((prev) => prev.slice(0, -1));
    setProposal(null);
    setHighlightedCells([]);
    toast.success("Action annulée");
  };

  const handleInit = async () => {
    if (!config.firstHorizontal || !config.firstVertical) {
      toast.error("Veuillez entrer les deux premiers mots");
      return;
    }
    setIsLoading(true);
    try {
      const data = await post("/crossword/init", {
        rows: config.rows, cols: config.cols,
        first_horizontal_word: config.firstHorizontal, first_vertical_word: config.firstVertical,
        session_id: sessionId,
      });
      setGridState({ grid: data.grid, rows: data.rows, cols: data.cols, words_placed: data.words_placed });
      setProposal(null);
      setRejectedWords([]);
      setHistory([]);
      toast.success(data.message);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erreur lors de l'initialisation");
    } finally { setIsLoading(false); }
  };

  const requestProposal = async (direction) => {
    setIsLoading(true);
    try {
      const data = await post("/crossword/propose", { grid_state: gridState, direction, session_id: sessionId });
      if (data.proposal) {
        setProposal(data.proposal);
        setRejectedWords([]);
        setHighlightedCells(buildHighlightCells(data.proposal, direction));
        toast.success(data.message);
      } else {
        if (data.grid) { saveToHistory(); setGridState((prev) => ({ ...prev, grid: data.grid })); }
        setProposal(null);
        setHighlightedCells([]);
        toast.info(data.message);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erreur lors de la proposition");
    } finally { setIsLoading(false); }
  };

  const handleAccept = async () => {
    if (!proposal) return;
    saveToHistory();
    setIsLoading(true);
    try {
      const data = await post("/crossword/place", {
        grid_state: gridState, word: proposal.word,
        direction: proposal.direction, row: proposal.row, col: proposal.col,
      });
      setGridState({ ...gridState, grid: data.grid, words_placed: data.words_placed });
      setProposal(null);
      setRejectedWords([]);
      setHighlightedCells([]);
      toast.success(data.message);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erreur lors du placement");
    } finally { setIsLoading(false); }
  };

  const handleReject = async () => {
    if (!proposal) return;
    const newRejected = [...rejectedWords, proposal.word];
    setRejectedWords(newRejected);
    setIsLoading(true);
    try {
      const data = await post("/crossword/reject", {
        grid_state: gridState, direction: proposal.direction,
        rejected_words: newRejected, session_id: sessionId,
      });
      if (data.proposal) {
        setProposal(data.proposal);
        setHighlightedCells(buildHighlightCells(data.proposal, data.proposal.direction));
        toast.success(data.message);
      } else {
        if (data.grid) { saveToHistory(); setGridState((prev) => ({ ...prev, grid: data.grid })); }
        setProposal(null);
        setHighlightedCells([]);
        toast.info(data.message);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erreur lors du rejet");
    } finally { setIsLoading(false); }
  };

  const handleFileUpload = async (file) => {
    const formData = new FormData();
    formData.append("file", file);
    setIsLoading(true);
    try {
      const data = await postForm("/words/upload", formData);
      setSessionId(data.session_id);
      setWordCount(data.word_count);
      setPriorityWords(data.words || []);
      toast.success(data.message);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erreur lors du chargement");
    } finally { setIsLoading(false); }
  };

  const handleFinish = async () => {
    saveToHistory();
    setIsLoading(true);
    try {
      const data = await post("/crossword/finish", { grid_state: gridState });
      setGridState((prev) => ({ ...prev, grid: data.grid }));
      setProposal(null);
      setHighlightedCells([]);
      toast.success(data.message);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erreur lors de la finalisation");
    } finally { setIsLoading(false); }
  };

  return (
    <div className="h-screen w-full flex flex-col md:flex-row overflow-hidden bg-white" data-testid="app-container">
      <Toaster position="top-center" richColors />
      <ConfigPanel config={config} setConfig={setConfig} onInit={handleInit} isLoading={isLoading}
        sessionId={sessionId} onFileUpload={handleFileUpload} wordCount={wordCount} priorityWords={priorityWords} />
      <CrosswordGrid grid={gridState.grid} rows={gridState.rows} cols={gridState.cols} highlightedCells={highlightedCells} />
      <ProposalPanel proposal={proposal} onAccept={handleAccept} onReject={handleReject}
        onRequestHorizontal={() => requestProposal("horizontal")} onRequestVertical={() => requestProposal("vertical")}
        onFinish={handleFinish} onUndo={handleUndo} canUndo={history.length > 0}
        isLoading={isLoading} wordsPlaced={gridState.words_placed} gridInitialized={gridState.grid.length > 0} />
    </div>
  );
}

export default App;
