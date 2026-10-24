# Résultats sur vraies photos

Généré par `scripts/process_real.py` le 2026-10-24 17:36, OpenCV 5.0.0.

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
| L3 | +0.20 | 4 | 1 | +0.14, +0.14, +0.07, -0.06 |
| L4 | +0.00 | 4 | 0 | -0.08, -0.00, -0.07, -0.06 |
| L5 | +0.50 | 4 | 4 | +0.27, +0.51, +0.38, +0.51 |
| L6 | +0.00 | 4 | 0 | -0.23, +0.03, -0.13, +0.04 |
| L7 | +0.50 | 4 | 3 | +0.31, +0.48, +0.41, +0.58 |
| L8 | +0.00 | 2 | 0 | -0.20, -0.15 |

- Traits élargis (vrai > 0) : signalés 8/12 comparaisons ; traits inchangés : signalés à tort 1/17

## E3 — fissure-A (répétabilité, pas de vérité terrain)

- Photos : 5 ; mesurées sans demande de reprise : 5
- Largeur médiane (médiane des photos, fissure la plus longue) : 3.718 mm
- Coefficient de variation entre photos :
  - fissure la plus longue de chaque photo (ancien indicateur) : médiane 16.1 %, max 8.9 %
  - zone de suivi (feuille de la carte + 10 cm, repère carte, même zone pour toutes les photos) : médiane 15.7 %, max 8.9 %
  - mêmes tronçons (cases de 10 mm de la zone vues par toutes les photos : 6) : médiane 17.3 %
  - analyse, pas une règle de l'app : photos vues à <= 10° en travers de la fissure (2) : zone —, mêmes tronçons —
- Décisions de l'agent (règles) : propose_ticket 5

| Photo | Décision | Plus longue : médiane (mm) | Zone : médiane (mm) | Zone : max (mm) | Mêmes tronçons (mm) | Angle en travers (°) | Zone cherchable | px/mm | ± (mm) |
|---|---|---|---|---|---|---|---|---|---|
| IMG_1592.heic | propose_ticket | 4.02 | 4.02 | 4.983 | 4.683 | 1.0 | 0.43 | 13.96 | 0.053 |
| IMG_1593.heic | propose_ticket | 4.247 | 4.128 | 5.011 | 4.52 | 6.5 | 0.93 | 6.74 | 0.077 |
| IMG_1594.heic | propose_ticket | 3.718 | 3.718 | 4.732 | 3.521 | 16.2 | 0.24 | 15.7 | 0.081 |
| IMG_1595.heic | propose_ticket | 2.807 | 2.775 | 3.983 | 3.186 | 20.4 | 0.51 | 12.19 | 0.095 |
| IMG_1596.heic | propose_ticket | 3.255 | 3.255 | 4.755 | 3.495 | 14.2 | 0.32 | 11.93 | 0.054 |

## E3 — fissure-B (répétabilité, pas de vérité terrain)

- Photos : 7 ; mesurées sans demande de reprise : 7
- Largeur médiane (médiane des photos, fissure la plus longue) : 6.044 mm
- Coefficient de variation entre photos :
  - fissure la plus longue de chaque photo (ancien indicateur) : médiane 12.0 %, max 14.1 %
  - zone de suivi (feuille de la carte + 10 cm, repère carte, même zone pour toutes les photos) : médiane 17.8 %, max 11.6 %
  - mêmes tronçons (cases de 10 mm de la zone vues par toutes les photos : 7) : médiane 16.7 %
  - analyse, pas une règle de l'app : photos vues à <= 10° en travers de la fissure (4) : zone 8.9 %, mêmes tronçons 15.9 %
- Décisions de l'agent (règles) : propose_ticket 7

| Photo | Décision | Plus longue : médiane (mm) | Zone : médiane (mm) | Zone : max (mm) | Mêmes tronçons (mm) | Angle en travers (°) | Zone cherchable | px/mm | ± (mm) |
|---|---|---|---|---|---|---|---|---|---|
| IMG_1599.heic | propose_ticket | 5.675 | 5.066 | 7.773 | 5.444 | 8.3 | 0.43 | 12.41 | 0.067 |
| IMG_1600.heic | propose_ticket | 6.521 | 3.858 | 7.303 | 7.019 | 23.0 | 0.35 | 12.61 | 0.037 |
| IMG_1601.heic | propose_ticket | 4.69 | 3.192 | 5.772 | 4.774 | 16.7 | 0.49 | 10.94 | 0.087 |
| IMG_1602.heic | propose_ticket | 6.044 | 5.69 | 6.824 | 5.568 | 6.8 | 0.23 | 14.9 | 0.041 |
| IMG_1603.heic | propose_ticket | 6.32 | 4.768 | 6.516 | 6.386 | 24.2 | 0.24 | 14.98 | 0.03 |
| IMG_1604.heic | propose_ticket | 6.381 | 4.704 | 8.289 | 6.585 | 3.4 | 0.97 | 5.09 | 0.121 |
| IMG_1605.heic | propose_ticket | 5.097 | 4.765 | 7.151 | 4.441 | 2.9 | 0.43 | 12.38 | 0.102 |

## E3 — beton-deux-cartes (répétabilité, pas de vérité terrain)

- Photos : 5 ; mesurées sans demande de reprise : 5
- Largeur médiane (médiane des photos, fissure la plus longue) : 4.859 mm
- Coefficient de variation entre photos :
  - fissure la plus longue de chaque photo (ancien indicateur) : médiane 4.7 %, max 3.4 %
  - zone de suivi (feuille de la carte + 10 cm, repère carte, même zone pour toutes les photos) : médiane 2.9 %, max 3.4 %
  - mêmes tronçons (cases de 10 mm de la zone vues par toutes les photos : 34) : médiane 3.0 %
  - analyse, pas une règle de l'app : photos vues à <= 10° en travers de la fissure (3) : zone 0.7 %, mêmes tronçons 2.0 %
- Décisions de l'agent (règles) : propose_ticket 5

| Photo | Décision | Plus longue : médiane (mm) | Zone : médiane (mm) | Zone : max (mm) | Mêmes tronçons (mm) | Angle en travers (°) | Zone cherchable | px/mm | ± (mm) |
|---|---|---|---|---|---|---|---|---|---|
| IMG_1641.heic | propose_ticket | 4.71 | 4.71 | 5.851 | 4.775 | 14.7 | 0.84 | 5.66 | 0.114 |
| IMG_1642.heic | propose_ticket | 4.551 | 4.52 | 6.326 | 4.458 | 18.1 | 0.9 | 5.46 | 0.139 |
| IMG_1644.heic | propose_ticket | 5.09 | 4.875 | 5.934 | 4.818 | 8.1 | 0.97 | 4.37 | 0.131 |
| IMG_1645.heic | propose_ticket | 4.859 | 4.806 | 5.85 | 4.637 | 8.3 | 0.96 | 6.1 | 0.117 |
| IMG_1646.heic | propose_ticket | 5.047 | 4.822 | 5.863 | 4.688 | 8.3 | 0.97 | 6.63 | 0.099 |

## E3 — beton-imprimee (répétabilité, pas de vérité terrain)

- Photos : 2 ; mesurées sans demande de reprise : 2
- Largeur médiane (médiane des photos, fissure la plus longue) : 5.034 mm
- Coefficient de variation entre photos :
  - fissure la plus longue de chaque photo (ancien indicateur) : médiane —, max —
  - zone de suivi (feuille de la carte + 10 cm, repère carte, même zone pour toutes les photos) : médiane —, max —
  - mêmes tronçons (cases de 10 mm de la zone vues par toutes les photos : 37) : médiane —
  - analyse, pas une règle de l'app : photos vues à <= 10° en travers de la fissure (1) : zone —, mêmes tronçons —
- Décisions de l'agent (règles) : propose_ticket 2

| Photo | Décision | Plus longue : médiane (mm) | Zone : médiane (mm) | Zone : max (mm) | Mêmes tronçons (mm) | Angle en travers (°) | Zone cherchable | px/mm | ± (mm) |
|---|---|---|---|---|---|---|---|---|---|
| IMG_1639.heic | propose_ticket | 5.081 | 4.894 | 5.98 | 4.779 | 7.3 | 0.83 | 6.55 | 0.086 |
| IMG_1640.heic | propose_ticket | 4.986 | 4.775 | 5.929 | 4.734 | 11.0 | 0.72 | 6.71 | 0.09 |

## E3 — enduit-deux-cartes (répétabilité, pas de vérité terrain)

- Photos : 8 ; mesurées sans demande de reprise : 8
- Largeur médiane (médiane des photos, fissure la plus longue) : 4.202 mm
- Coefficient de variation entre photos :
  - fissure la plus longue de chaque photo (ancien indicateur) : médiane 15.6 %, max 7.6 %
  - zone de suivi (feuille de la carte + 10 cm, repère carte, même zone pour toutes les photos) : médiane 14.8 %, max 7.1 %
  - mêmes tronçons (cases de 10 mm de la zone vues par toutes les photos : 61) : médiane 15.0 %
  - analyse, pas une règle de l'app : photos vues à <= 10° en travers de la fissure (7) : zone 13.3 %, mêmes tronçons 12.3 %
- Décisions de l'agent (règles) : propose_ticket 8

| Photo | Décision | Plus longue : médiane (mm) | Zone : médiane (mm) | Zone : max (mm) | Mêmes tronçons (mm) | Angle en travers (°) | Zone cherchable | px/mm | ± (mm) |
|---|---|---|---|---|---|---|---|---|---|
| IMG_1631.heic | propose_ticket | 4.092 | 2.749 | 7.922 | 3.537 | 5.7 | 0.72 | 7.33 | 0.131 |
| IMG_1632.heic | propose_ticket | 3.833 | 3.515 | 7.909 | 4.174 | 6.3 | 0.97 | 5.56 | 0.119 |
| IMG_1633.heic | propose_ticket | 4.5 | 3.253 | 8.2 | 4.711 | 6.2 | 0.81 | 6.29 | 0.117 |
| IMG_1634.heic | propose_ticket | 2.797 | 2.698 | 8.108 | 3.254 | 1.8 | 0.94 | 6.38 | 0.104 |
| IMG_1635.heic | propose_ticket | 4.02 | 3.244 | 8.059 | 3.754 | 0.7 | 0.95 | 6.29 | 0.119 |
| IMG_1636.heic | propose_ticket | 5.024 | 4.11 | 9.706 | 5.163 | 13.6 | 0.96 | 6.63 | 0.122 |
| IMG_1637.heic | propose_ticket | 4.371 | 3.608 | 8.192 | 4.211 | 3.4 | 0.97 | 5.86 | 0.119 |
| IMG_1638.heic | propose_ticket | 4.312 | 3.872 | 8.638 | 4.122 | 9.6 | 0.97 | 4.58 | 0.14 |

## E3 — enduit-imprimee (répétabilité, pas de vérité terrain)

- Photos : 4 ; mesurées sans demande de reprise : 4
- Largeur médiane (médiane des photos, fissure la plus longue) : 4.316 mm
- Coefficient de variation entre photos :
  - fissure la plus longue de chaque photo (ancien indicateur) : médiane 25.9 %, max 9.9 %
  - zone de suivi (feuille de la carte + 10 cm, repère carte, même zone pour toutes les photos) : médiane 30.0 %, max 10.9 %
  - mêmes tronçons (cases de 10 mm de la zone vues par toutes les photos : 95) : médiane 6.7 %
  - analyse, pas une règle de l'app : photos vues à <= 10° en travers de la fissure (3) : zone 36.9 %, mêmes tronçons 2.7 %
- Décisions de l'agent (règles) : propose_ticket 4

| Photo | Décision | Plus longue : médiane (mm) | Zone : médiane (mm) | Zone : max (mm) | Mêmes tronçons (mm) | Angle en travers (°) | Zone cherchable | px/mm | ± (mm) |
|---|---|---|---|---|---|---|---|---|---|
| IMG_1627.heic | propose_ticket | 4.912 | 4.17 | 8.87 | 4.069 | 8.8 | 0.96 | 6.31 | 0.125 |
| IMG_1628.heic | propose_ticket | 5.39 | 4.184 | 8.677 | 3.942 | 6.5 | 0.91 | 6.31 | 0.126 |
| IMG_1629.heic | propose_ticket | 2.979 | 1.975 | 6.989 | 4.156 | 9.0 | 0.97 | 4.57 | 0.167 |
| IMG_1630.heic | propose_ticket | 3.719 | 3.501 | 7.686 | 3.562 | 10.2 | 0.73 | 8.4 | 0.136 |

