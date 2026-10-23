# Résultats sur vraies photos

Généré par `scripts/process_real.py` le 2026-10-23 22:38, OpenCV 5.0.0.

Règle de 50 mm de la carte imprimée mesurée à 50.0 mm : facteur d'échelle 1.0000 appliqué aux vraies fissures (E3). Les traits de la mire (E2/E4) n'en dépendent pas : carte et traits sont imprimés ensemble.

## E2 — mire imprimée v1

- Photos : 4 ; carte détectée et mesure faite : 4

| Trait | Largeur nominale (mm) | Détecté (photos) | Médiane mesurée (mm) | Erreur absolue moyenne (mm) | Biais (mm) |
|---|---|---|---|---|---|
| L1 | 0.20 | 4/4 | 0.252 | 0.125 | +0.103 |
| L2 | 0.30 | 4/4 | 0.312 | 0.079 | +0.060 |
| L3 | 0.50 | 4/4 | 0.486 | 0.038 | +0.002 |
| L4 | 0.70 | 4/4 | 0.714 | 0.018 | +0.018 |
| L5 | 1.00 | 4/4 | 0.960 | 0.042 | -0.042 |
| L6 | 1.50 | 4/4 | 1.440 | 0.062 | -0.062 |
| L7 | 2.00 | 4/4 | 2.008 | 0.052 | -0.022 |
| L8 | 3.00 | 4/4 | 3.017 | 0.075 | -0.029 |

- Erreur absolue moyenne, tous traits et toutes photos : **0.061 mm** (médiane 0.031 mm, 32 mesures)
- Plus petite largeur détectée sur au moins 80 % des photos : **0.20 mm**
- Limite : la largeur imprimée réelle des traits n'a pas été contrôlée au scanner ; l'étalement de l'encre peut l'élargir de quelques centièmes de mm.

## E2 — mire imprimée v2

- Photos : 8 ; carte détectée et mesure faite : 8

| Trait | Largeur nominale (mm) | Détecté (photos) | Médiane mesurée (mm) | Erreur absolue moyenne (mm) | Biais (mm) |
|---|---|---|---|---|---|
| L1 | 0.20 | 7/8 | 0.216 | 0.036 | +0.021 |
| L2 | 0.30 | 8/8 | 0.324 | 0.075 | +0.067 |
| L3 | 0.70 | 8/8 | 0.613 | 0.100 | -0.100 |
| L4 | 0.70 | 8/8 | 0.716 | 0.034 | -0.001 |
| L5 | 1.50 | 8/8 | 1.477 | 0.071 | -0.056 |
| L6 | 1.50 | 8/8 | 1.466 | 0.078 | -0.061 |
| L7 | 2.50 | 8/8 | 2.540 | 0.101 | +0.018 |
| L8 | 3.00 | 6/8 | 3.034 | 0.104 | +0.008 |

- Erreur absolue moyenne, tous traits et toutes photos : **0.075 mm** (médiane 0.055 mm, 61 mesures)
- Plus petite largeur détectée sur au moins 80 % des photos : **0.20 mm**
- Limite : la largeur imprimée réelle des traits n'a pas été contrôlée au scanner ; l'étalement de l'encre peut l'élargir de quelques centièmes de mm.

## E4 réel — deux « visites » de la mire (v1 puis v2)

| Trait | v1 nominal | v2 nominal | Écart vrai (mm) | Écart mesuré, médiane (mm) | Rallongé de |
|---|---|---|---|---|---|
| L1 | 0.20 | 0.20 | +0.00 | -0.036 | 0 mm |
| L2 | 0.30 | 0.30 | +0.00 | +0.011 | 10 mm |
| L3 | 0.50 | 0.70 | +0.20 | +0.126 | 0 mm |
| L4 | 0.70 | 0.70 | +0.00 | +0.003 | 0 mm |
| L5 | 1.00 | 1.50 | +0.50 | +0.517 | 0 mm |
| L6 | 1.50 | 1.50 | +0.00 | +0.026 | 10 mm |
| L7 | 2.00 | 2.50 | +0.50 | +0.532 | 0 mm |
| L8 | 3.00 | 3.00 | +0.00 | +0.017 | 0 mm |

- Erreur absolue moyenne sur l'écart de largeur (par trait, médianes des photos) : **0.027 mm**
- Comparaisons photo à photo v1→v2 : 4 ; élargissement significatif détecté : 4/4 ; rallongement détecté (> 4 mm) : 4/4

Test par tronçon de ~10 mm (`change.py` : fissure entière + chaque tronçon, seuil de Bonferroni à 5 % par paire, changement >= 0,1 mm). Un trait compte comme « signalé » si l'un de ses tronçons l'est.

| Trait | Écart vrai (mm) | Paires où le trait est comparé | Signalé élargi | Écart médian par paire (mm) |
|---|---|---|---|---|
| L1 | +0.00 | 3 | 0 | -0.02, -0.10, -0.34 |
| L2 | +0.00 | 4 | 1 | +0.38, +0.03, +0.00, -0.23 |
| L3 | +0.20 | 4 | 1 | +0.15, +0.14, +0.07, -0.06 |
| L4 | +0.00 | 4 | 0 | -0.08, -0.00, -0.07, -0.06 |
| L5 | +0.50 | 4 | 4 | +0.28, +0.51, +0.37, +0.51 |
| L6 | +0.00 | 4 | 0 | -0.23, +0.03, -0.13, +0.04 |
| L7 | +0.50 | 4 | 3 | +0.31, +0.48, +0.41, +0.58 |
| L8 | +0.00 | 2 | 0 | -0.20, -0.15 |

- Traits élargis (vrai > 0) : signalés 8/12 comparaisons ; traits inchangés : signalés à tort 1/17

## E3 — fissure-A (répétabilité, pas de vérité terrain)

- Photos : 5 ; mesurées sans demande de reprise : 5
- Largeur médiane (médiane des photos, fissure la plus longue) : 3.718 mm
- Coefficient de variation entre photos :
  - fissure la plus longue de chaque photo (ancien indicateur) : médiane 18.0 %, max 14.5 %
  - zone de suivi (feuille de la carte + 40 mm, repère carte, même zone pour toutes les photos) : médiane 17.7 %, max 16.0 %
  - mêmes tronçons (cases de 10 mm de la zone vues par toutes les photos : 3) : médiane 24.3 %
  - analyse, pas une règle de l'app : photos vues à <= 10° en travers de la fissure (2) : zone —, mêmes tronçons —
- Décisions de l'agent (règles) : propose_ticket 5

| Photo | Décision | Plus longue : médiane (mm) | Zone : médiane (mm) | Zone : max (mm) | Mêmes tronçons (mm) | Angle en travers (°) | Zone cherchable | px/mm | ± (mm) |
|---|---|---|---|---|---|---|---|---|---|
| IMG_1592.heic | propose_ticket | 4.468 | 4.101 | 5.052 | 4.885 | 0.3 | 0.76 | 14.41 | 0.068 |
| IMG_1593.heic | propose_ticket | 4.815 | 4.308 | 5.022 | 4.816 | 5.6 | 0.9 | 6.82 | 0.083 |
| IMG_1594.heic | propose_ticket | 3.718 | 3.304 | 4.582 | 3.799 | 16.2 | 0.58 | 15.7 | 0.081 |
| IMG_1595.heic | propose_ticket | 3.04 | 2.794 | 3.308 | 2.787 | 22.1 | 0.9 | 12.34 | 0.107 |
| IMG_1596.heic | propose_ticket | 3.627 | 3.267 | 4.298 | 3.171 | 13.2 | 0.67 | 16.53 | 0.068 |

## E3 — fissure-B (répétabilité, pas de vérité terrain)

- Photos : 7 ; mesurées sans demande de reprise : 7
- Largeur médiane (médiane des photos, fissure la plus longue) : 4.943 mm
- Coefficient de variation entre photos :
  - fissure la plus longue de chaque photo (ancien indicateur) : médiane 45.4 %, max 30.8 %
  - zone de suivi (feuille de la carte + 40 mm, repère carte, même zone pour toutes les photos) : médiane 15.3 %, max 14.7 %
  - mêmes tronçons (cases de 10 mm de la zone vues par toutes les photos : 4) : médiane 14.3 %
  - analyse, pas une règle de l'app : photos vues à <= 10° en travers de la fissure (2) : zone —, mêmes tronçons —
- Décisions de l'agent (règles) : propose_ticket 7

| Photo | Décision | Plus longue : médiane (mm) | Zone : médiane (mm) | Zone : max (mm) | Mêmes tronçons (mm) | Angle en travers (°) | Zone cherchable | px/mm | ± (mm) |
|---|---|---|---|---|---|---|---|---|---|
| IMG_1599.heic | propose_ticket | 6.185 | 4.973 | 7.799 | 5.796 | 10.4 | 0.76 | 12.29 | 0.073 |
| IMG_1600.heic | propose_ticket | 3.312 | 3.711 | 7.098 | 5.348 | 26.3 | 0.74 | 12.51 | 0.04 |
| IMG_1601.heic | propose_ticket | 0.558 | 3.906 | 5.865 | 5.107 | 16.7 | 0.87 | 14.26 | 0.069 |
| IMG_1602.heic | propose_ticket | 6.279 | 5.213 | 6.828 | 5.192 | 16.2 | 0.53 | 14.87 | 0.043 |
| IMG_1603.heic | propose_ticket | 6.39 | 3.629 | 6.393 | 4.347 | 24.2 | 0.59 | 14.84 | 0.03 |
| IMG_1604.heic | propose_ticket | 4.943 | 5.076 | 9.146 | 6.834 | 3.3 | 0.9 | 4.98 | 0.105 |
| IMG_1605.heic | propose_ticket | 4.822 | 4.615 | 7.155 | 5.101 | 2.7 | 0.76 | 12.36 | 0.123 |

