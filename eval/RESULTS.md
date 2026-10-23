# Résultats d'évaluation (synthétique)

Généré par `scripts/run_eval.py` le 2026-10-23 22:52, OpenCV 5.0.0.

## E1 — largeur de fissure (images synthétiques)

- Images: 300; carte détectée: 299 (99.7 %); fissure détectée (>=10 points appariés): 258 (86.0 %)
- Points appariés: 67988; MAE point par point: **0.146 mm** (biais +0.088, médiane |e| 0.067, P90 |e| 0.279); ligne de base transformée de distance (pixel entier): MAE 0.386 mm
- Erreur relative point par point: médiane 5.3 %, P90 44.2 %
- Par image (fissure principale + branches): MAE largeur max **0.260 mm** (biais +0.130), MAE largeur médiane **0.123 mm** (biais +0.099)
- Couverture de la fissure (rappel) moyenne 0.87; précision des points 0.84
- Couverture de l'incertitude annoncée (|erreur médiane| <= 2 sigma): 83 % des images
- Temps de calcul par image (Mac M2, 1 cœur par image): médiane 14.83 s, P95 26.84 s

| Largeur vraie (mm) | points | MAE (mm) | biais (mm) | MAE relative médiane | MAE base DT (mm) |
|---|---|---|---|---|---|
| 0.1–0.3 | 5321 | 0.244 | +0.191 | 36.3 % | 0.140 |
| 0.3–0.5 | 9570 | 0.139 | +0.060 | 20.1 % | 0.153 |
| 0.5–1.0 | 14359 | 0.151 | +0.072 | 8.8 % | 0.250 |
| 1.0–2.0 | 17647 | 0.127 | +0.075 | 3.9 % | 0.439 |
| 2.0–3.0 | 13823 | 0.141 | +0.104 | 2.8 % | 0.581 |
| 3.0–6.0 | 7258 | 0.129 | +0.075 | 2.1 % | 0.640 |

| Largeur vraie en pixels photo | points | MAE (mm) | MAE relative médiane |
|---|---|---|---|
| 0–1 px | 1079 | 0.412 | 56.3 % |
| 1–2 px | 7475 | 0.213 | 35.3 % |
| 2–4 px | 15459 | 0.158 | 15.0 % |
| 4–8 px | 14784 | 0.140 | 5.1 % |
| 8–100 px | 29191 | 0.116 | 2.6 % |

| Inclinaison | images détectées | MAE largeur max (mm) | MAE largeur médiane (mm) |
|---|---|---|---|
| 0–15° | 92 | 0.272 | 0.102 |
| 15–30° | 87 | 0.183 | 0.090 |
| 30–46° | 79 | 0.332 | 0.183 |

Cas d'échec (69 / 300) :

| image | raison | largeur base (mm) | px/mm photo | incl. (°) | flou (px) | reflet | bougé (px) | distracteurs | err. max (mm) |
|---|---|---|---|---|---|---|---|---|---|
| e1_20000 | erreur largeur max > max(0,3 mm, 30 %) | 0.97 | 4.1 | 38 | 1.70 |  | 7 |  | +1.32 |
| e1_20004 | erreur largeur max > max(0,3 mm, 30 %) | 1.41 | 4.6 | 30 | 1.54 |  |  | joint | +3.19 |
| e1_20009 | erreur largeur max > max(0,3 mm, 30 %) | 0.57 | 4.1 | 3 | 1.15 |  | 4 |  | +0.58 |
| e1_20017 | fissure non détectée | 0.80 | 4.0 | 16 | 0.60 | oui |  |  tache | +nan |
| e1_20020 | fissure non détectée | 0.61 | 3.5 | 1 | 1.54 |  |  |  tache | +nan |
| e1_20021 | fissure non détectée | 0.38 | 3.0 | 18 | 0.96 |  |  |  | +nan |
| e1_20022 | erreur largeur max > max(0,3 mm, 30 %) | 0.80 | 6.9 | 23 | 1.58 |  |  |  | +0.34 |
| e1_20024 | fissure non détectée | 0.21 | 3.1 | 40 | 1.03 |  |  |  | +nan |
| e1_20026 | erreur largeur max > max(0,3 mm, 30 %) | 0.54 | 5.7 | 19 | 1.23 |  | 9 |  | +0.53 |
| e1_20027 | erreur largeur max > max(0,3 mm, 30 %) | 0.79 | 2.9 | 44 | 1.76 |  |  |  | +0.32 |
| e1_20028 | erreur largeur max > max(0,3 mm, 30 %) | 0.34 | 3.8 | 32 | 1.65 |  |  |  | +0.95 |
| e1_20030 | erreur largeur max > max(0,3 mm, 30 %) | 0.59 | 3.3 | 11 | 0.85 |  |  | joint | +0.37 |
| e1_20034 | fissure non détectée | 0.20 | 4.3 | 8 | 0.78 | oui |  |  | +nan |
| e1_20044 | erreur largeur max > max(0,3 mm, 30 %) | 1.09 | 4.0 | 23 | 1.08 |  | 8 |  | +0.89 |
| e1_20045 | erreur largeur max > max(0,3 mm, 30 %) | 0.29 | 4.5 | 35 | 0.65 |  |  |  | +1.45 |
| e1_20046 | fissure non détectée | 0.39 | 2.9 | 31 | 1.13 |  | 8 |  | +nan |
| e1_20047 | fissure non détectée | 0.67 | 4.2 | 21 | 0.62 | oui | 8 |  tache | +nan |
| e1_20048 | erreur largeur max > max(0,3 mm, 30 %) | 0.74 | 3.5 | 15 | 1.42 |  |  |  | +0.82 |
| e1_20052 | carte non détectée | 2.44 | 4.1 | 35 | 0.60 |  | 8 | joint tache | +nan |
| e1_20057 | erreur largeur max > max(0,3 mm, 30 %) | 1.20 | 2.8 | 21 | 0.69 |  |  | joint | +3.18 |
| e1_20059 | fissure non détectée | 0.43 | 2.7 | 41 | 1.17 |  |  | joint | +nan |
| e1_20062 | erreur largeur max > max(0,3 mm, 30 %) | 0.57 | 4.3 | 42 | 1.40 |  |  |  | +0.47 |
| e1_20074 | fissure non détectée | 0.27 | 4.6 | 6 | 1.60 |  | 9 |  tache | +nan |
| e1_20083 | fissure non détectée | 0.39 | 3.2 | 13 | 1.08 |  |  |  | +nan |
| e1_20088 | fissure non détectée | 0.21 | 3.4 | 14 | 1.79 |  |  |  | +nan |
| e1_20090 | erreur largeur max > max(0,3 mm, 30 %) | 0.23 | 3.7 | 35 | 0.63 |  |  | joint | +5.60 |
| e1_20093 | fissure non détectée | 0.24 | 3.3 | 37 | 0.80 |  | 3 | joint | +nan |
| e1_20094 | fissure non détectée | 0.38 | 5.3 | 15 | 1.60 |  |  |  | +nan |
| e1_20097 | fissure non détectée | 0.36 | 5.3 | 23 | 1.51 | oui | 3 |  | +nan |
| e1_20103 | fissure non détectée | 0.72 | 4.8 | 24 | 1.75 | oui |  |  | +nan |
| e1_20111 | fissure non détectée | 0.26 | 3.7 | 16 | 1.44 |  |  |  | +nan |
| e1_20114 | fissure non détectée | 0.41 | 5.7 | 2 | 1.76 |  |  |  | +nan |
| e1_20119 | fissure non détectée | 1.11 | 3.1 | 43 | 1.61 |  |  |  | +nan |
| e1_20122 | fissure non détectée | 1.36 | 3.5 | 38 | 0.60 |  |  |  | +nan |
| e1_20128 | fissure non détectée | 0.76 | 3.6 | 16 | 0.82 |  | 9 |  | +nan |
| e1_20130 | fissure non détectée | 2.00 | 5.0 | 15 | 1.37 |  | 7 | joint | +nan |
| e1_20131 | erreur largeur max > max(0,3 mm, 30 %) | 0.44 | 3.0 | 7 | 0.52 |  |  | joint | +0.53 |
| e1_20144 | fissure non détectée | 0.87 | 4.2 | 40 | 0.53 |  |  | joint | +nan |
| e1_20145 | fissure non détectée | 0.97 | 4.6 | 26 | 0.81 |  |  |  | +nan |
| e1_20148 | erreur largeur max > max(0,3 mm, 30 %) | 0.45 | 6.8 | 44 | 1.73 |  |  |  | +0.92 |
| e1_20166 | erreur largeur max > max(0,3 mm, 30 %) | 0.31 | 3.8 | 10 | 1.21 |  |  |  | +0.41 |
| e1_20167 | erreur largeur max > max(0,3 mm, 30 %) | 0.39 | 6.2 | 3 | 0.66 |  | 7 | joint | +1.05 |
| e1_20174 | erreur largeur max > max(0,3 mm, 30 %) | 1.20 | 3.5 | 34 | 1.78 |  |  |  | +0.51 |
| e1_20185 | fissure non détectée | 0.24 | 3.1 | 28 | 1.68 |  |  |  | +nan |
| e1_20187 | erreur largeur max > max(0,3 mm, 30 %) | 0.25 | 4.9 | 38 | 1.06 |  |  |  | +0.42 |
| e1_20193 | erreur largeur max > max(0,3 mm, 30 %) | 0.21 | 7.5 | 25 | 1.52 |  | 9 |  | +0.41 |
| e1_20202 | erreur largeur max > max(0,3 mm, 30 %) | 0.59 | 3.1 | 4 | 1.72 |  |  |  | +0.60 |
| e1_20204 | erreur largeur max > max(0,3 mm, 30 %) | 2.76 | 7.4 | 10 | 1.78 |  |  |  | +3.12 |
| e1_20206 | fissure non détectée | 1.54 | 4.1 | 6 | 1.27 |  |  |  tache | +nan |
| e1_20213 | fissure non détectée | 0.27 | 5.5 | 2 | 1.72 |  | 7 |  | +nan |
| e1_20220 | fissure non détectée | 0.24 | 2.8 | 28 | 0.59 |  |  |  | +nan |
| e1_20228 | fissure non détectée | 0.25 | 6.0 | 5 | 1.28 |  |  |  | +nan |
| e1_20232 | erreur largeur max > max(0,3 mm, 30 %) | 0.21 | 8.1 | 33 | 0.57 |  |  |  | +1.37 |
| e1_20234 | fissure non détectée | 0.42 | 3.7 | 41 | 0.82 |  |  |  tache | +nan |
| e1_20235 | fissure non détectée | 0.22 | 7.7 | 15 | 1.57 |  |  |  tache | +nan |
| e1_20236 | fissure non détectée | 2.50 | 3.5 | 14 | 0.51 | oui |  |  | +nan |
| e1_20253 | fissure non détectée | 0.46 | 3.1 | 36 | 0.58 |  |  |  | +nan |
| e1_20255 | erreur largeur max > max(0,3 mm, 30 %) | 0.64 | 3.4 | 7 | 0.55 |  |  |  | +3.96 |
| e1_20261 | fissure non détectée | 0.39 | 3.5 | 18 | 0.64 |  | 8 |  | +nan |
| e1_20265 | fissure non détectée | 0.41 | 4.8 | 0 | 1.06 |  | 8 |  | +nan |
| e1_20267 | fissure non détectée | 0.52 | 4.8 | 38 | 0.96 |  |  |  | +nan |
| e1_20271 | fissure non détectée | 0.23 | 3.6 | 21 | 1.13 |  | 5 |  | +nan |
| e1_20282 | fissure non détectée | 0.38 | 3.6 | 3 | 1.16 |  |  |  | +nan |
| e1_20283 | fissure non détectée | 0.34 | 3.6 | 5 | 1.25 |  |  |  | +nan |
| e1_20285 | fissure non détectée | 0.46 | 3.1 | 16 | 0.86 | oui |  | joint tache | +nan |
| e1_20286 | fissure non détectée | 2.60 | 5.9 | 2 | 1.30 |  |  |  | +nan |
| e1_20288 | erreur largeur max > max(0,3 mm, 30 %) | 0.35 | 3.3 | 30 | 0.82 |  |  |  | +0.52 |
| e1_20293 | erreur largeur max > max(0,3 mm, 30 %) | 0.27 | 3.7 | 5 | 1.06 |  |  |  tache | +4.71 |
| e1_20294 | fissure non détectée | 0.24 | 3.8 | 37 | 1.36 |  | 5 |  tache | +nan |

## E4 — évolution entre deux visites (paires synthétiques)

- Paires: 40; comparables (fissure mesurée aux deux visites): 38
- Non comparables : e4_70016 (v1=no_crack_found, v2=ok), e4_70034 (no common crack: no v2 point lies on a v1 crack)
- Recalage, carte restée en place: 25 paires, erreur médiane 0.00 mm, P90 0.00 mm, modes {'card_frame': 25}
- Recalage, carte recollée (déplacée): 13 paires, erreur médiane 0.04 mm, P90 0.09 mm, modes {'texture_homography': 13}
- Élargissement (médiane des écarts point à point): MAE **0.083 mm**, biais +0.005 mm
- Alerte « évolution » (élargissement ou allongement significatif): précision 1.00, rappel 0.80, fausses alertes sur paires sans changement 0/8
- Allongement: MAE longueur nouvelle 4.1 mm (vrai 0/8/15 mm)
- Tronçons de ~10 mm testés sur les paires sans élargissement : 42 ; déclarés élargis à tort : 4

| élargissement vrai (mm) | paires | écart mesuré médian (mm) | MAE (mm) | détecté significatif |
|---|---|---|---|---|
| 0.0 | 12 | -0.009 | 0.076 | 8 % |
| 0.1 | 5 | +0.116 | 0.144 | 60 % |
| 0.2 | 6 | +0.197 | 0.076 | 50 % |
| 0.3 | 6 | +0.313 | 0.024 | 100 % |
| 0.5 | 5 | +0.530 | 0.053 | 100 % |
| 1.0 | 4 | +0.972 | 0.167 | 100 % |
