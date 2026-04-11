# Générateur de Mots Croisés - PRD

## Problem Statement
Construire un générateur de mots croisés basé sur une liste exhaustive de mots français. L'utilisateur configure les dimensions de la grille, entre les premiers mots horizontal et vertical, puis le système propose automatiquement des mots suivants basés sur les lettres existantes.

## User Personas
- Créateurs de mots croisés amateurs
- Enseignants de français
- Passionnés de jeux de mots

## Core Requirements (Static)
1. Configuration grille (lignes/colonnes 5-20)
2. Saisie premiers mots horizontal et vertical
3. Cases noires automatiques après chaque mot
4. Proposition de mots basée sur contraintes
5. Validation/Rejet des propositions
6. Upload dictionnaire personnalisé

## What's Been Implemented (Jan 2026)
- [x] Backend FastAPI avec tous les endpoints
- [x] Liste de ~2500 mots français intégrée
- [x] Algorithme de proposition de mots (les plus longs en priorité)
- [x] Upload de fichiers .txt personnalisés
- [x] Frontend React avec layout 3 colonnes Swiss Brutalist
- [x] Grille interactive avec cases noires
- [x] Boutons Valider/Rejeter
- [x] Toast notifications
- [x] Tests automatisés passants

## Tech Stack
- Backend: FastAPI + Python
- Frontend: React + Tailwind CSS
- Database: MongoDB (configured but not heavily used)
- UI: Swiss Brutalist theme, IBM Plex fonts

## API Endpoints
- POST /api/crossword/init - Initialiser grille
- POST /api/crossword/propose - Proposer un mot
- POST /api/crossword/reject - Rejeter et reproposer
- POST /api/crossword/place - Placer un mot
- POST /api/words/upload - Upload dictionnaire
- GET /api/words/count - Compter les mots

## Prioritized Backlog
### P0 (Critical) - Done
- [x] Création grille de base
- [x] Proposition de mots

### P1 (Important) - Future
- [ ] Export grille en image/PDF
- [ ] Sauvegarde des grilles créées
- [ ] Mode impression

### P2 (Nice to have) - Future
- [ ] Génération automatique complète
- [ ] Partage de grilles
- [ ] Thèmes visuels
