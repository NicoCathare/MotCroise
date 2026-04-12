import { useState, useCallback } from "react";
import "@/App.css";
import axios from "axios";
import { Upload, RefreshCw, Check, X, Grid3X3, ArrowRight, ArrowDown, Square, Undo2 } from "lucide-react";
import { Toaster, toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// Configuration Panel Component
const ConfigPanel = ({ config, setConfig, onInit, isLoading, sessionId, onFileUpload, wordCount }) => {
  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (file) {
      onFileUpload(file);
    }
  };

  return (
    <div className="w-full md:w-80 border-r border-[#E5E5E5] bg-[#F9F9F9] p-6 flex flex-col gap-6 overflow-y-auto">
      <div>
        <h1 className="font-heading text-2xl font-bold tracking-tight text-[#0A0A0A]" data-testid="app-title">
          Générateur de Mots Croisés
        </h1>
        <p className="text-sm text-[#0A0A0A]/60 mt-2">
          Créez votre grille de mots croisés
        </p>
      </div>

      {/* Grid Size */}
      <div className="flex flex-col gap-4">
        <label className="label-swiss">Dimensions de la grille</label>
        <div className="flex gap-4">
          <div className="flex-1">
            <label className="text-xs text-[#0A0A0A]/60 mb-1 block">Lignes</label>
            <input
              type="number"
              min="5"
              max="20"
              value={config.rows}
              onChange={(e) => setConfig({ ...config, rows: parseInt(e.target.value) || 5 })}
              className="input-swiss w-full"
              data-testid="input-rows"
            />
          </div>
          <div className="flex-1">
            <label className="text-xs text-[#0A0A0A]/60 mb-1 block">Colonnes</label>
            <input
              type="number"
              min="5"
              max="20"
              value={config.cols}
              onChange={(e) => setConfig({ ...config, cols: parseInt(e.target.value) || 5 })}
              className="input-swiss w-full"
              data-testid="input-cols"
            />
          </div>
        </div>
      </div>

      {/* First Words */}
      <div className="flex flex-col gap-4">
        <label className="label-swiss">Premiers mots</label>
        <div>
          <label className="text-xs text-[#0A0A0A]/60 mb-1 flex items-center gap-1">
            <ArrowRight size={12} /> Mot horizontal
          </label>
          <input
            type="text"
            value={config.firstHorizontal}
            onChange={(e) => setConfig({ ...config, firstHorizontal: e.target.value })}
            placeholder="ex: MAISON"
            className="input-swiss w-full uppercase"
            data-testid="input-horizontal"
          />
        </div>
        <div>
          <label className="text-xs text-[#0A0A0A]/60 mb-1 flex items-center gap-1">
            <ArrowDown size={12} /> Mot vertical
          </label>
          <input
            type="text"
            value={config.firstVertical}
            onChange={(e) => setConfig({ ...config, firstVertical: e.target.value })}
            placeholder="ex: ARBRE"
            className="input-swiss w-full uppercase"
            data-testid="input-vertical"
          />
        </div>
      </div>

      {/* Init Button */}
      <button
        onClick={onInit}
        disabled={isLoading || !config.firstHorizontal || !config.firstVertical}
        className="btn-primary flex items-center justify-center gap-2"
        data-testid="btn-init"
      >
        <Grid3X3 size={18} />
        Créer la grille
      </button>

      {/* Separator */}
      <div className="border-t border-[#E5E5E5]" />

      {/* File Upload */}
      <div className="flex flex-col gap-3">
        <label className="label-swiss">Dictionnaire personnalisé</label>
        <label className="upload-zone" data-testid="upload-zone">
          <Upload size={24} className="text-[#0A0A0A]/40" />
          <span className="text-sm text-[#0A0A0A]/60">
            {sessionId ? "Fichier chargé" : "Charger un fichier .txt"}
          </span>
          <input
            type="file"
            accept=".txt"
            onChange={handleFileChange}
            className="hidden"
            data-testid="input-file"
          />
        </label>
        <p className="text-xs text-[#0A0A0A]/40">
          {wordCount} mots disponibles {sessionId && "(personnalisé)"}
        </p>
      </div>
    </div>
  );
};

// Crossword Grid Component
const CrosswordGrid = ({ grid, rows, cols, highlightedCells }) => {
  if (!grid || grid.length === 0) {
    return (
      <div className="flex-1 flex flex-col bg-white p-8 overflow-y-auto items-center justify-center">
        <div className="text-center">
          <Grid3X3 size={64} className="text-[#0A0A0A]/10 mx-auto mb-4" />
          <p className="text-[#0A0A0A]/40 text-lg">
            Configurez et créez votre grille
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-white p-8 overflow-y-auto items-center justify-center" data-testid="grid-container">
      <div
        className="crossword-grid"
        style={{
          gridTemplateColumns: `repeat(${cols}, minmax(32px, 48px))`,
          gridTemplateRows: `repeat(${rows}, minmax(32px, 48px))`,
        }}
        data-testid="crossword-grid"
      >
        {grid.map((row, rowIdx) =>
          row.map((cell, colIdx) => {
            const isBlocked = cell === "#";
            const isEmpty = cell === "";
            const isHighlighted = highlightedCells?.some(
              (h) => h.row === rowIdx && h.col === colIdx
            );

            return (
              <div
                key={`${rowIdx}-${colIdx}`}
                className={`crossword-cell ${isBlocked ? "blocked" : ""} ${isEmpty ? "empty" : ""} ${isHighlighted ? "active" : ""}`}
                data-testid={`cell-${rowIdx}-${colIdx}`}
              >
                {!isBlocked && cell}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

// Word Proposal Panel Component
const ProposalPanel = ({
  proposal,
  onAccept,
  onReject,
  onRequestHorizontal,
  onRequestVertical,
  onFinish,
  onUndo,
  canUndo,
  isLoading,
  wordsPlaced,
  gridInitialized,
}) => {
  return (
    <div className="w-full md:w-96 border-l border-[#E5E5E5] bg-[#F9F9F9] p-6 flex flex-col gap-6 overflow-y-auto">
      <div>
        <h2 className="font-heading text-xl font-bold tracking-tight text-[#0A0A0A]">
          Propositions
        </h2>
        <p className="text-sm text-[#0A0A0A]/60 mt-1">
          Acceptez ou rejetez les mots proposés
        </p>
      </div>

      {/* Request buttons */}
      {gridInitialized && (
        <div className="flex flex-col gap-3">
          <button
            onClick={onRequestHorizontal}
            disabled={isLoading}
            className="btn-secondary flex items-center justify-center gap-2"
            data-testid="btn-request-horizontal"
          >
            <ArrowRight size={16} />
            Proposer mot horizontal
          </button>
          <button
            onClick={onRequestVertical}
            disabled={isLoading}
            className="btn-secondary flex items-center justify-center gap-2"
            data-testid="btn-request-vertical"
          >
            <ArrowDown size={16} />
            Proposer mot vertical
          </button>
          <button
            onClick={onFinish}
            disabled={isLoading}
            className="btn-primary flex items-center justify-center gap-2 bg-[#0A0A0A] hover:bg-[#333]"
            data-testid="btn-finish"
          >
            <Square size={16} />
            Terminer
          </button>
          <button
            onClick={onUndo}
            disabled={isLoading || !canUndo}
            className="btn-destructive flex items-center justify-center gap-2"
            data-testid="btn-undo"
          >
            <Undo2 size={16} />
            Annuler
          </button>
        </div>
      )}

      {/* Current Proposal */}
      {proposal && (
        <div className="proposal-card" data-testid="proposal-card">
          <div>
            <label className="label-swiss">Mot proposé</label>
            <p className="font-mono text-2xl font-bold mt-2 text-[#002FA7]" data-testid="proposed-word">
              {proposal.original_word}
            </p>
          </div>
          <div className="flex gap-2 text-sm text-[#0A0A0A]/60">
            <span className="flex items-center gap-1">
              {proposal.direction === "horizontal" ? (
                <ArrowRight size={14} />
              ) : (
                <ArrowDown size={14} />
              )}
              {proposal.direction === "horizontal" ? "Horizontal" : "Vertical"}
            </span>
            <span>•</span>
            <span>Ligne {proposal.row + 1}, Col {proposal.col + 1}</span>
          </div>
          <div className="flex gap-3 mt-2">
            <button
              onClick={onAccept}
              disabled={isLoading}
              className="btn-primary flex-1 flex items-center justify-center gap-2"
              data-testid="btn-accept"
            >
              <Check size={16} />
              Valider
            </button>
            <button
              onClick={onReject}
              disabled={isLoading}
              className="btn-destructive flex-1 flex items-center justify-center gap-2"
              data-testid="btn-reject"
            >
              <X size={16} />
              Rejeter
            </button>
          </div>
        </div>
      )}

      {isLoading && (
        <div className="flex items-center justify-center p-4">
          <RefreshCw size={24} className="animate-spin text-[#002FA7]" />
        </div>
      )}

      {/* Words Placed List */}
      {wordsPlaced && wordsPlaced.length > 0 && (
        <div className="flex flex-col gap-3">
          <label className="label-swiss">Mots placés ({wordsPlaced.length})</label>
          <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
            {wordsPlaced.map((word, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between bg-white border border-[#E5E5E5] px-3 py-2"
                data-testid={`placed-word-${idx}`}
              >
                <span className="font-mono font-semibold">{word.original || word.word}</span>
                <span className="text-xs text-[#0A0A0A]/40 flex items-center gap-1">
                  {word.direction === "horizontal" ? (
                    <ArrowRight size={12} />
                  ) : (
                    <ArrowDown size={12} />
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

// Main App Component
function App() {
  const [config, setConfig] = useState({
    rows: 10,
    cols: 10,
    firstHorizontal: "",
    firstVertical: "",
  });

  const [gridState, setGridState] = useState({
    grid: [],
    rows: 0,
    cols: 0,
    words_placed: [],
  });

  const [proposal, setProposal] = useState(null);
  const [rejectedWords, setRejectedWords] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [wordCount, setWordCount] = useState(0);
  const [highlightedCells, setHighlightedCells] = useState([]);
  const [history, setHistory] = useState([]);

  // Fetch word count on mount
  const fetchWordCount = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/words/count`, {
        params: sessionId ? { session_id: sessionId } : {},
      });
      setWordCount(response.data.count);
    } catch (error) {
      console.error("Error fetching word count:", error);
    }
  }, [sessionId]);

  useState(() => {
    fetchWordCount();
  }, [fetchWordCount]);

  // Save current state to history before any grid modification
  const saveToHistory = () => {
    setHistory((prev) => [...prev, JSON.parse(JSON.stringify(gridState))]);
  };

  // Undo last action
  const handleUndo = () => {
    if (history.length === 0) return;
    const previousState = history[history.length - 1];
    setGridState(previousState);
    setHistory((prev) => prev.slice(0, -1));
    setProposal(null);
    setHighlightedCells([]);
    toast.success("Action annulée");
  };

  // Initialize grid
  const handleInit = async () => {
    if (!config.firstHorizontal || !config.firstVertical) {
      toast.error("Veuillez entrer les deux premiers mots");
      return;
    }

    setIsLoading(true);
    try {
      const response = await axios.post(`${API}/crossword/init`, {
        rows: config.rows,
        cols: config.cols,
        first_horizontal_word: config.firstHorizontal,
        first_vertical_word: config.firstVertical,
        session_id: sessionId,
      });

      setGridState({
        grid: response.data.grid,
        rows: response.data.rows,
        cols: response.data.cols,
        words_placed: response.data.words_placed,
      });
      setProposal(null);
      setRejectedWords([]);
      setHistory([]);
      toast.success(response.data.message);
    } catch (error) {
      const message = error.response?.data?.detail || "Erreur lors de l'initialisation";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  // Request word proposal
  const requestProposal = async (direction) => {
    setIsLoading(true);
    try {
      const response = await axios.post(`${API}/crossword/propose`, {
        grid_state: gridState,
        direction,
        session_id: sessionId,
      });

      if (response.data.proposal) {
        setProposal(response.data.proposal);
        setRejectedWords([]);
        // Highlight cells where word will be placed
        const cells = [];
        const p = response.data.proposal;
        for (let i = 0; i < p.length; i++) {
          if (direction === "horizontal") {
            cells.push({ row: p.row, col: p.col + i });
          } else {
            cells.push({ row: p.row + i, col: p.col });
          }
        }
        setHighlightedCells(cells);
        toast.success(response.data.message);
      } else {
        // No word found: update grid with black cells if returned
        if (response.data.grid) {
          saveToHistory();
          setGridState((prev) => ({
            ...prev,
            grid: response.data.grid,
          }));
        }
        setProposal(null);
        setHighlightedCells([]);
        toast.info(response.data.message);
      }
    } catch (error) {
      const message = error.response?.data?.detail || "Erreur lors de la proposition";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  // Accept proposal
  const handleAccept = async () => {
    if (!proposal) return;

    saveToHistory();
    setIsLoading(true);
    try {
      const response = await axios.post(`${API}/crossword/place`, {
        grid_state: gridState,
        word: proposal.word,
        direction: proposal.direction,
        row: proposal.row,
        col: proposal.col,
      });

      setGridState({
        ...gridState,
        grid: response.data.grid,
        words_placed: response.data.words_placed,
      });
      setProposal(null);
      setRejectedWords([]);
      setHighlightedCells([]);
      toast.success(response.data.message);
    } catch (error) {
      const message = error.response?.data?.detail || "Erreur lors du placement";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  // Reject proposal
  const handleReject = async () => {
    if (!proposal) return;

    const newRejected = [...rejectedWords, proposal.word];
    setRejectedWords(newRejected);

    setIsLoading(true);
    try {
      const response = await axios.post(`${API}/crossword/reject`, {
        grid_state: gridState,
        direction: proposal.direction,
        rejected_words: newRejected,
        session_id: sessionId,
      });

      if (response.data.proposal) {
        setProposal(response.data.proposal);
        // Highlight cells where word will be placed
        const cells = [];
        const p = response.data.proposal;
        for (let i = 0; i < p.length; i++) {
          if (p.direction === "horizontal") {
            cells.push({ row: p.row, col: p.col + i });
          } else {
            cells.push({ row: p.row + i, col: p.col });
          }
        }
        setHighlightedCells(cells);
        toast.success(response.data.message);
      } else {
        // No word found: update grid with black cells if returned
        if (response.data.grid) {
          saveToHistory();
          setGridState((prev) => ({
            ...prev,
            grid: response.data.grid,
          }));
        }
        setProposal(null);
        setHighlightedCells([]);
        toast.info(response.data.message);
      }
    } catch (error) {
      const message = error.response?.data?.detail || "Erreur lors du rejet";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  // File upload
  const handleFileUpload = async (file) => {
    const formData = new FormData();
    formData.append("file", file);

    setIsLoading(true);
    try {
      const response = await axios.post(`${API}/words/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setSessionId(response.data.session_id);
      setWordCount(response.data.word_count);
      toast.success(response.data.message);
    } catch (error) {
      const message = error.response?.data?.detail || "Erreur lors du chargement";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  // Finish grid - fill all empty cells with black
  const handleFinish = async () => {
    saveToHistory();
    setIsLoading(true);
    try {
      const response = await axios.post(`${API}/crossword/finish`, {
        grid_state: gridState,
      });
      setGridState((prev) => ({
        ...prev,
        grid: response.data.grid,
      }));
      setProposal(null);
      setHighlightedCells([]);
      toast.success(response.data.message);
    } catch (error) {
      const message = error.response?.data?.detail || "Erreur lors de la finalisation";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="h-screen w-full flex flex-col md:flex-row overflow-hidden bg-white" data-testid="app-container">
      <Toaster position="top-center" richColors />
      
      <ConfigPanel
        config={config}
        setConfig={setConfig}
        onInit={handleInit}
        isLoading={isLoading}
        sessionId={sessionId}
        onFileUpload={handleFileUpload}
        wordCount={wordCount}
      />

      <CrosswordGrid
        grid={gridState.grid}
        rows={gridState.rows}
        cols={gridState.cols}
        highlightedCells={highlightedCells}
      />

      <ProposalPanel
        proposal={proposal}
        onAccept={handleAccept}
        onReject={handleReject}
        onRequestHorizontal={() => requestProposal("horizontal")}
        onRequestVertical={() => requestProposal("vertical")}
        onFinish={handleFinish}
        onUndo={handleUndo}
        canUndo={history.length > 0}
        isLoading={isLoading}
        wordsPlaced={gridState.words_placed}
        gridInitialized={gridState.grid.length > 0}
      />
    </div>
  );
}

export default App;
