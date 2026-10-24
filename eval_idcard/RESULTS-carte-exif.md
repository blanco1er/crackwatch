# Carte bancaire comme référence d'échelle — évaluation synthétique

Généré par `scripts/eval_idcard.py` le 2026-10-24 17:10, OpenCV 5.0.0, graines 50000–50199.
Mode EXIF : la vraie focale est donnée au détecteur (comme si l'app envoyait FocalLengthIn35mmFilm).

- Scènes : 200 ; carte acceptée : 134 (67 %) ; statuts : ok 134, card_occluded 39, card_too_oblique 16, card_not_found 8, card_too_small 3
- Dans le domaine annoncé (inclinaison ≤ 40°, carte ≥ 3,2 px/mm) : 125/164 acceptées (76 %)

Erreur d'échelle relative au centre de la fissure (pire direction) :

- Carte bancaire (ID-1, épaisseur corrigée) : médiane 0.44 %, P90 1.11 %, P95 1.62 %, max 8.83 % (n=134)
- même chose sans correction d'épaisseur : médiane 0.61 %, P90 1.40 %, P95 1.85 %, max 8.52 % (n=134)
- Carte ChArUco imprimée, mêmes scènes : médiane 0.04 %, P90 0.12 %, P95 0.15 %, max 0.26 % (n=134)
- Carte bancaire, au centre de la carte : médiane 0.37 %, P90 0.93 %, P95 1.01 %, max 3.13 % (n=134)
- Biais moyen (moyenne des deux valeurs singulières − 1) : -0.01 % ± 0.79 %
- Incertitude annoncée (1 σ) : médiane 1.95 % ; erreur ≤ 2 σ dans 99 % des cas, ≤ 3 σ dans 99 %

| Doigt | scènes | acceptées | erreur médiane | P90 | bord reconstruit | refus « card_occluded » |
|---|---|---|---|---|---|---|
| none | 91 | 70 | 0.47 % | 0.98 % | 3 | 9 |
| short_mid | 19 | 14 | 0.48 % | 1.09 % | 1 | 3 |
| long_mid | 12 | 9 | 0.23 % | 0.39 % | 0 | 1 |
| corner | 20 | 16 | 0.45 % | 1.54 % | 0 | 3 |
| short_full | 17 | 0 | — | — | 0 | 14 |
| press_centre | 17 | 13 | 0.49 % | 1.09 % | 1 | 2 |
| hand_long | 24 | 12 | 0.48 % | 1.82 % | 4 | 7 |

| Inclinaison | acceptées | erreur médiane carte | P90 | erreur médiane ChArUco |
|---|---|---|---|---|
| 0–15° | 50 | 0.46 % | 0.98 % | 0.03 % |
| 15–30° | 53 | 0.33 % | 1.26 % | 0.03 % |
| 30–41° | 31 | 0.52 % | 1.12 % | 0.05 % |
| 41–60° | 0 | — | — | — |

- Flou estimé sur les bords de la carte vs vrai : erreur médiane +0.08 px, MAE 0.18 px
- Temps de détection : médiane 3.79 s, P95 9.00 s
