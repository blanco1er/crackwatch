# Carte bancaire comme référence d'échelle — évaluation synthétique

Généré par `scripts/eval_idcard.py` le 2026-10-24 01:49, OpenCV 5.0.0, graines 52000–52119.

- Scènes : 120 ; carte acceptée : 75 (62 %) ; statuts : ok 75, card_occluded 26, card_not_found 6, card_too_small 5, card_too_oblique 4, card_wrong_size 4
- Dans le domaine annoncé (inclinaison ≤ 40°, carte ≥ 3,2 px/mm) : 73/98 acceptées (74 %)

Erreur d'échelle relative au centre de la fissure (pire direction) :

- Carte bancaire (ID-1, épaisseur corrigée) : médiane 0.73 %, P90 1.71 %, P95 3.33 %, max 5.94 % (n=75)
- même chose sans correction d'épaisseur : médiane 0.73 %, P90 1.87 %, P95 3.00 %, max 6.19 % (n=75)
- Carte ChArUco imprimée, mêmes scènes : médiane 0.03 %, P90 0.10 %, P95 0.14 %, max 0.20 % (n=75)
- Carte bancaire, au centre de la carte : médiane 0.41 %, P90 0.85 %, P95 0.95 %, max 10.43 % (n=75)
- Biais moyen (moyenne des deux valeurs singulières − 1) : -0.01 % ± 1.14 %
- Incertitude annoncée (1 σ) : médiane 0.94 % ; erreur ≤ 2 σ dans 93 % des cas, ≤ 3 σ dans 99 %

| Doigt | scènes | acceptées | erreur médiane | P90 | bord reconstruit | refus « card_occluded » |
|---|---|---|---|---|---|---|
| none | 70 | 52 | 0.74 % | 1.68 % | 3 | 11 |
| short_mid | 11 | 9 | 0.55 % | 1.52 % | 0 | 2 |
| long_mid | 9 | 6 | 0.76 % | 1.09 % | 0 | 1 |
| corner | 11 | 7 | 0.42 % | 1.32 % | 0 | 1 |
| short_full | 19 | 1 | 5.94 % | 5.94 % | 1 | 11 |

| Inclinaison | acceptées | erreur médiane carte | P90 | erreur médiane ChArUco |
|---|---|---|---|---|
| 0–15° | 37 | 0.46 % | 1.29 % | 0.03 % |
| 15–30° | 24 | 1.02 % | 3.12 % | 0.03 % |
| 30–41° | 13 | 0.55 % | 1.32 % | 0.06 % |
| 41–60° | 1 | 5.57 % | 5.57 % | 0.02 % |

- Flou estimé sur les bords de la carte vs vrai : erreur médiane +0.10 px, MAE 0.19 px
- Temps de détection : médiane 2.10 s, P95 4.73 s

Largeur de fissure, mêmes scènes, les deux références (fissure détectée par les deux) :

- largeur max : MAE ChArUco **0.319 mm** (biais +0.239) ; MAE carte bancaire **0.306 mm** (biais +0.210) ; écart médian entre les deux |b − a| 0.068 mm (n=67)
- largeur médiane : MAE ChArUco **0.097 mm** (biais +0.063) ; MAE carte bancaire **0.115 mm** (biais +0.096) ; écart médian entre les deux |b − a| 0.051 mm (n=67)
- Rapport des largeurs médianes carte/ChArUco − 1 : médiane 2.14 %, P90 |.| 23.17 %
- Fissure détectée : ChArUco 105/120, carte bancaire 67/120
