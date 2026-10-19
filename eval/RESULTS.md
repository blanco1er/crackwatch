# Résultats d'évaluation (synthétique)

Généré par `scripts/run_eval.py` le 2026-10-18 00:43, OpenCV 5.0.0.

## E1 — largeur de fissure (images synthétiques)

- Images: 300; carte détectée: 299 (99.7 %); fissure détectée (>=10 points appariés): 259 (86.3 %)
- Points appariés: 64973; MAE point par point: **0.211 mm** (biais +0.110, médiane |e| 0.098, P90 |e| 0.420); ligne de base transformée de distance (pixel entier): MAE 0.444 mm
- Erreur relative point par point: médiane 7.8 %, P90 68.7 %
- Par image (fissure principale + branches): MAE largeur max **0.374 mm** (biais +0.273), MAE largeur médiane **0.174 mm** (biais +0.131)
- Couverture de la fissure (rappel) moyenne 0.86; précision des points 0.84
- Couverture de l'incertitude annoncée (|erreur médiane| <= 2 sigma): 71 % des images
- Temps de calcul par image (Mac M2, 1 cœur par image): médiane 5.88 s, P95 9.53 s

| Largeur vraie (mm) | points | MAE (mm) | biais (mm) | MAE relative médiane | MAE base DT (mm) |
|---|---|---|---|---|---|
| 0.1–0.3 | 4835 | 0.259 | +0.157 | 51.8 % | 0.126 |
| 0.3–0.5 | 9181 | 0.201 | +0.069 | 29.7 % | 0.176 |
| 0.5–1.0 | 13709 | 0.219 | +0.071 | 14.4 % | 0.329 |
| 1.0–2.0 | 17515 | 0.189 | +0.105 | 5.5 % | 0.568 |
| 2.0–3.0 | 12945 | 0.221 | +0.153 | 4.0 % | 0.619 |
| 3.0–6.0 | 6777 | 0.211 | +0.138 | 3.1 % | 0.611 |

| Largeur vraie en pixels photo | points | MAE (mm) | MAE relative médiane |
|---|---|---|---|
| 0–1 px | 1068 | 0.461 | 95.3 % |
| 1–2 px | 6903 | 0.270 | 50.4 % |
| 2–4 px | 14978 | 0.228 | 22.8 % |
| 4–8 px | 14404 | 0.209 | 7.7 % |
| 8–100 px | 27620 | 0.179 | 3.6 % |

| Inclinaison | images détectées | MAE largeur max (mm) | MAE largeur médiane (mm) |
|---|---|---|---|
| 0–15° | 91 | 0.366 | 0.176 |
| 15–30° | 88 | 0.296 | 0.125 |
| 30–46° | 80 | 0.469 | 0.224 |

Cas d'échec (92 / 300) :

| image | raison | largeur base (mm) | px/mm photo | incl. (°) | flou (px) | reflet | bougé (px) | distracteurs | err. max (mm) |
|---|---|---|---|---|---|---|---|---|---|
| e1_20000 | erreur largeur max > max(0,3 mm, 30 %) | 0.97 | 4.1 | 38 | 1.70 |  | 7 |  | +1.64 |
| e1_20004 | erreur largeur max > max(0,3 mm, 30 %) | 1.41 | 4.6 | 30 | 1.54 |  |  | joint | +3.44 |
| e1_20009 | erreur largeur max > max(0,3 mm, 30 %) | 0.57 | 4.1 | 3 | 1.15 |  | 4 |  | +0.80 |
| e1_20011 | erreur largeur max > max(0,3 mm, 30 %) | 0.26 | 3.3 | 18 | 0.50 |  |  |  | +0.85 |
| e1_20017 | fissure non détectée | 0.80 | 4.0 | 16 | 0.60 | oui |  |  tache | +nan |
| e1_20019 | erreur largeur max > max(0,3 mm, 30 %) | 0.28 | 3.3 | 44 | 0.63 | oui |  |  | +0.35 |
| e1_20020 | fissure non détectée | 0.61 | 3.5 | 1 | 1.54 |  |  |  tache | +nan |
| e1_20021 | fissure non détectée | 0.38 | 3.0 | 18 | 0.96 |  |  |  | +nan |
| e1_20022 | erreur largeur max > max(0,3 mm, 30 %) | 0.80 | 6.9 | 23 | 1.58 |  |  |  | +0.62 |
| e1_20024 | fissure non détectée | 0.21 | 3.1 | 40 | 1.03 |  |  |  | +nan |
| e1_20026 | erreur largeur max > max(0,3 mm, 30 %) | 0.54 | 5.7 | 19 | 1.23 |  | 9 |  | +0.59 |
| e1_20027 | erreur largeur max > max(0,3 mm, 30 %) | 0.79 | 2.9 | 44 | 1.76 |  |  |  | +0.57 |
| e1_20028 | fissure non détectée | 0.34 | 3.8 | 32 | 1.65 |  |  |  | +nan |
| e1_20030 | erreur largeur max > max(0,3 mm, 30 %) | 0.59 | 3.3 | 11 | 0.85 |  |  | joint | +2.12 |
| e1_20032 | erreur largeur max > max(0,3 mm, 30 %) | 0.54 | 4.7 | 38 | 1.42 |  |  |  | +0.34 |
| e1_20034 | fissure non détectée | 0.20 | 4.3 | 8 | 0.78 | oui |  |  | +nan |
| e1_20044 | erreur largeur max > max(0,3 mm, 30 %) | 1.09 | 4.0 | 23 | 1.08 |  | 8 |  | +2.63 |
| e1_20046 | fissure non détectée | 0.39 | 2.9 | 31 | 1.13 |  | 8 |  | +nan |
| e1_20047 | fissure non détectée | 0.67 | 4.2 | 21 | 0.62 | oui | 8 |  tache | +nan |
| e1_20048 | erreur largeur max > max(0,3 mm, 30 %) | 0.74 | 3.5 | 15 | 1.42 |  |  |  | +1.36 |
| e1_20051 | fissure non détectée | 0.27 | 6.9 | 7 | 1.28 | oui |  |  | +nan |
| e1_20052 | carte non détectée | 2.44 | 4.1 | 35 | 0.60 |  | 8 | joint tache | +nan |
| e1_20055 | erreur largeur max > max(0,3 mm, 30 %) | 0.47 | 5.3 | 44 | 1.43 |  |  |  | +0.33 |
| e1_20057 | erreur largeur max > max(0,3 mm, 30 %) | 1.20 | 2.8 | 21 | 0.69 |  |  | joint | +1.11 |
| e1_20059 | fissure non détectée | 0.43 | 2.7 | 41 | 1.17 |  |  | joint | +nan |
| e1_20060 | erreur largeur max > max(0,3 mm, 30 %) | 1.24 | 3.1 | 20 | 1.22 |  |  |  | +2.32 |
| e1_20062 | erreur largeur max > max(0,3 mm, 30 %) | 0.57 | 4.3 | 42 | 1.40 |  |  |  | +0.64 |
| e1_20064 | erreur largeur max > max(0,3 mm, 30 %) | 0.56 | 3.4 | 29 | 0.61 | oui |  |  | +1.49 |
| e1_20069 | erreur largeur max > max(0,3 mm, 30 %) | 0.57 | 4.7 | 1 | 1.06 |  |  | joint | +0.37 |
| e1_20074 | fissure non détectée | 0.27 | 4.6 | 6 | 1.60 |  | 9 |  tache | +nan |
| e1_20076 | erreur largeur max > max(0,3 mm, 30 %) | 2.53 | 3.4 | 10 | 0.64 |  |  |  | +1.51 |
| e1_20083 | fissure non détectée | 0.39 | 3.2 | 13 | 1.08 |  |  |  | +nan |
| e1_20088 | fissure non détectée | 0.21 | 3.4 | 14 | 1.79 |  |  |  | +nan |
| e1_20090 | erreur largeur max > max(0,3 mm, 30 %) | 0.23 | 3.7 | 35 | 0.63 |  |  | joint | +5.90 |
| e1_20091 | erreur largeur max > max(0,3 mm, 30 %) | 0.75 | 4.3 | 45 | 0.91 | oui |  | joint | +1.29 |
| e1_20093 | fissure non détectée | 0.24 | 3.3 | 37 | 0.80 |  | 3 | joint | +nan |
| e1_20094 | fissure non détectée | 0.38 | 5.3 | 15 | 1.60 |  |  |  | +nan |
| e1_20097 | fissure non détectée | 0.36 | 5.3 | 23 | 1.51 | oui | 3 |  | +nan |
| e1_20099 | erreur largeur max > max(0,3 mm, 30 %) | 0.65 | 5.0 | 17 | 1.60 |  |  | joint | +0.32 |
| e1_20103 | fissure non détectée | 0.72 | 4.8 | 24 | 1.75 | oui |  |  | +nan |
| e1_20108 | erreur largeur max > max(0,3 mm, 30 %) | 2.17 | 4.5 | 33 | 1.09 |  |  |  | +0.91 |
| e1_20111 | fissure non détectée | 0.26 | 3.7 | 16 | 1.44 |  |  |  | +nan |
| e1_20114 | fissure non détectée | 0.41 | 5.7 | 2 | 1.76 |  |  |  | +nan |
| e1_20119 | erreur largeur max > max(0,3 mm, 30 %) | 1.11 | 3.1 | 43 | 1.61 |  |  |  | +0.83 |
| e1_20124 | erreur largeur max > max(0,3 mm, 30 %) | 0.50 | 3.3 | 2 | 0.70 |  |  |  | +0.42 |
| e1_20128 | fissure non détectée | 0.76 | 3.6 | 16 | 0.82 |  | 9 |  | +nan |
| e1_20130 | erreur largeur max > max(0,3 mm, 30 %) | 2.00 | 5.0 | 15 | 1.37 |  | 7 | joint | +1.75 |
| e1_20131 | erreur largeur max > max(0,3 mm, 30 %) | 0.44 | 3.0 | 7 | 0.52 |  |  | joint | +0.47 |
| e1_20144 | fissure non détectée | 0.87 | 4.2 | 40 | 0.53 |  |  | joint | +nan |
| e1_20145 | erreur largeur max > max(0,3 mm, 30 %) | 0.97 | 4.6 | 26 | 0.81 |  |  |  | +0.56 |
| e1_20148 | erreur largeur max > max(0,3 mm, 30 %) | 0.45 | 6.8 | 44 | 1.73 |  |  |  | +1.90 |
| e1_20160 | erreur largeur max > max(0,3 mm, 30 %) | 0.33 | 3.3 | 21 | 0.53 |  |  | joint | +2.28 |
| e1_20166 | erreur largeur max > max(0,3 mm, 30 %) | 0.31 | 3.8 | 10 | 1.21 |  |  |  | +0.46 |
| e1_20167 | erreur largeur max > max(0,3 mm, 30 %) | 0.39 | 6.2 | 3 | 0.66 |  | 7 | joint | +2.73 |
| e1_20172 | erreur largeur max > max(0,3 mm, 30 %) | 2.18 | 5.2 | 20 | 1.33 |  |  | joint | +1.23 |
| e1_20174 | erreur largeur max > max(0,3 mm, 30 %) | 1.20 | 3.5 | 34 | 1.78 |  |  |  | +2.75 |
| e1_20177 | erreur largeur max > max(0,3 mm, 30 %) | 2.67 | 7.8 | 41 | 1.78 | oui |  |  | +1.29 |
| e1_20184 | erreur largeur max > max(0,3 mm, 30 %) | 0.30 | 6.6 | 27 | 1.74 |  |  |  | -0.37 |
| e1_20185 | fissure non détectée | 0.24 | 3.1 | 28 | 1.68 |  |  |  | +nan |
| e1_20187 | erreur largeur max > max(0,3 mm, 30 %) | 0.25 | 4.9 | 38 | 1.06 |  |  |  | +0.41 |
| e1_20193 | erreur largeur max > max(0,3 mm, 30 %) | 0.21 | 7.5 | 25 | 1.52 |  | 9 |  | +0.49 |
| e1_20195 | fissure non détectée | 0.27 | 6.9 | 18 | 1.63 |  |  |  tache | +nan |
| e1_20198 | erreur largeur max > max(0,3 mm, 30 %) | 0.35 | 3.8 | 2 | 0.54 |  | 3 |  tache | +0.41 |
| e1_20200 | erreur largeur max > max(0,3 mm, 30 %) | 0.46 | 4.3 | 35 | 1.36 |  |  |  | +0.38 |
| e1_20202 | erreur largeur max > max(0,3 mm, 30 %) | 0.59 | 3.1 | 4 | 1.72 |  |  |  | +1.00 |
| e1_20204 | erreur largeur max > max(0,3 mm, 30 %) | 2.76 | 7.4 | 10 | 1.78 |  |  |  | +3.06 |
| e1_20206 | fissure non détectée | 1.54 | 4.1 | 6 | 1.27 |  |  |  tache | +nan |
| e1_20213 | fissure non détectée | 0.27 | 5.5 | 2 | 1.72 |  | 7 |  | +nan |
| e1_20220 | fissure non détectée | 0.24 | 2.8 | 28 | 0.59 |  |  |  | +nan |
| e1_20222 | erreur largeur max > max(0,3 mm, 30 %) | 0.60 | 3.5 | 22 | 1.44 |  |  |  | +0.47 |
| e1_20228 | fissure non détectée | 0.25 | 6.0 | 5 | 1.28 |  |  |  | +nan |
| e1_20229 | erreur largeur max > max(0,3 mm, 30 %) | 0.49 | 2.9 | 39 | 0.67 |  |  | joint | +1.76 |
| e1_20232 | erreur largeur max > max(0,3 mm, 30 %) | 0.21 | 8.1 | 33 | 0.57 |  |  |  | +0.80 |
| e1_20234 | fissure non détectée | 0.42 | 3.7 | 41 | 0.82 |  |  |  tache | +nan |
| e1_20235 | fissure non détectée | 0.22 | 7.7 | 15 | 1.57 |  |  |  tache | +nan |
| e1_20236 | fissure non détectée | 2.50 | 3.5 | 14 | 0.51 | oui |  |  | +nan |
| e1_20246 | erreur largeur max > max(0,3 mm, 30 %) | 2.83 | 8.1 | 42 | 1.26 |  |  |  | +2.17 |
| e1_20253 | fissure non détectée | 0.46 | 3.1 | 36 | 0.58 |  |  |  | +nan |
| e1_20255 | erreur largeur max > max(0,3 mm, 30 %) | 0.64 | 3.4 | 7 | 0.55 |  |  |  | +0.43 |
| e1_20260 | erreur largeur max > max(0,3 mm, 30 %) | 0.43 | 4.2 | 13 | 1.25 |  |  |  | +0.34 |
| e1_20261 | fissure non détectée | 0.39 | 3.5 | 18 | 0.64 |  | 8 |  | +nan |
| e1_20265 | fissure non détectée | 0.41 | 4.8 | 0 | 1.06 |  | 8 |  | +nan |
| e1_20267 | fissure non détectée | 0.52 | 4.8 | 38 | 0.96 |  |  |  | +nan |
| e1_20271 | fissure non détectée | 0.23 | 3.6 | 21 | 1.13 |  | 5 |  | +nan |
| e1_20282 | fissure non détectée | 0.38 | 3.6 | 3 | 1.16 |  |  |  | +nan |
| e1_20283 | fissure non détectée | 0.34 | 3.6 | 5 | 1.25 |  |  |  | +nan |
| e1_20285 | fissure non détectée | 0.46 | 3.1 | 16 | 0.86 | oui |  | joint tache | +nan |
| e1_20286 | fissure non détectée | 2.60 | 5.9 | 2 | 1.30 |  |  |  | +nan |
| e1_20288 | erreur largeur max > max(0,3 mm, 30 %) | 0.35 | 3.3 | 30 | 0.82 |  |  |  | +0.61 |
| e1_20293 | erreur largeur max > max(0,3 mm, 30 %) | 0.27 | 3.7 | 5 | 1.06 |  |  |  tache | +6.51 |
| e1_20294 | fissure non détectée | 0.24 | 3.8 | 37 | 1.36 |  | 5 |  tache | +nan |
| e1_20299 | erreur largeur max > max(0,3 mm, 30 %) | 0.37 | 6.9 | 7 | 1.66 |  | 7 |  | +0.40 |

## E4 — évolution entre deux visites (paires synthétiques)

- Paires: 40; comparables (fissure mesurée aux deux visites): 39
- Recalage, carte restée en place: 26 paires, erreur médiane 0.00 mm, P90 0.00 mm, modes {'card_frame': 25, 'texture_homography': 1}
- Recalage, carte recollée (déplacée): 13 paires, erreur médiane 0.04 mm, P90 0.09 mm, modes {'texture_homography': 13}
- Élargissement (médiane des écarts point à point): MAE **0.069 mm**, biais -0.007 mm
- Alerte « évolution » (élargissement ou allongement significatif): précision 1.00, rappel 0.94, fausses alertes sur paires sans changement 0/8
- Allongement: MAE longueur nouvelle 4.0 mm (vrai 0/8/15 mm)

| élargissement vrai (mm) | paires | écart mesuré médian (mm) | MAE (mm) | détecté significatif |
|---|---|---|---|---|
| 0.0 | 12 | -0.004 | 0.061 | 8 % |
| 0.1 | 5 | +0.153 | 0.071 | 100 % |
| 0.2 | 6 | +0.204 | 0.043 | 83 % |
| 0.3 | 6 | +0.273 | 0.039 | 100 % |
| 0.5 | 5 | +0.479 | 0.055 | 100 % |
| 1.0 | 5 | +0.966 | 0.168 | 100 % |
