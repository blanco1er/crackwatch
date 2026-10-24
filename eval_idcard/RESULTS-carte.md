# Carte bancaire comme référence d'échelle — évaluation synthétique

Généré par `scripts/eval_idcard.py` le 2026-10-24 17:00, OpenCV 5.0.0, graines 50000–50199.

- Scènes : 200 ; carte acceptée : 130 (65 %) ; statuts : ok 130, card_occluded 41, card_too_oblique 16, card_not_found 8, card_too_small 3, card_not_flat 2
- Dans le domaine annoncé (inclinaison ≤ 40°, carte ≥ 3,2 px/mm) : 123/164 acceptées (75 %)

Erreur d'échelle relative au centre de la fissure (pire direction) :

- Carte bancaire (ID-1, épaisseur corrigée) : médiane 0.63 %, P90 2.31 %, P95 3.58 %, max 9.15 % (n=130)
- même chose sans correction d'épaisseur : médiane 0.80 %, P90 2.43 %, P95 3.83 %, max 8.78 % (n=130)
- Carte ChArUco imprimée, mêmes scènes : médiane 0.04 %, P90 0.12 %, P95 0.16 %, max 0.26 % (n=130)
- Carte bancaire, au centre de la carte : médiane 0.38 %, P90 0.88 %, P95 0.96 %, max 1.33 % (n=130)
- Biais moyen (moyenne des deux valeurs singulières − 1) : -0.02 % ± 1.30 %
- Incertitude annoncée (1 σ) : médiane 1.91 % ; erreur ≤ 2 σ dans 99 % des cas, ≤ 3 σ dans 99 %

| Doigt | scènes | acceptées | erreur médiane | P90 | bord reconstruit | refus « card_occluded » |
|---|---|---|---|---|---|---|
| none | 91 | 68 | 0.53 % | 1.54 % | 1 | 9 |
| short_mid | 19 | 15 | 1.11 % | 3.90 % | 1 | 2 |
| long_mid | 12 | 9 | 0.56 % | 0.94 % | 0 | 1 |
| corner | 20 | 16 | 0.74 % | 3.29 % | 0 | 3 |
| short_full | 17 | 0 | — | — | 0 | 14 |
| press_centre | 17 | 12 | 1.09 % | 2.70 % | 0 | 3 |
| hand_long | 24 | 10 | 0.69 % | 3.40 % | 2 | 9 |

| Inclinaison | acceptées | erreur médiane carte | P90 | erreur médiane ChArUco |
|---|---|---|---|---|
| 0–15° | 49 | 0.50 % | 1.53 % | 0.03 % |
| 15–30° | 51 | 0.67 % | 2.56 % | 0.03 % |
| 30–41° | 30 | 0.70 % | 2.74 % | 0.05 % |
| 41–60° | 0 | — | — | — |

- Flou estimé sur les bords de la carte vs vrai : erreur médiane +0.08 px, MAE 0.18 px
- Temps de détection : médiane 3.55 s, P95 8.69 s
