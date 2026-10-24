# Carte bancaire comme référence d'échelle — évaluation synthétique

Généré par `scripts/eval_idcard.py` le 2026-10-24 20:05, OpenCV 5.0.0, graines 50000–50199.

- Scènes : 200 ; carte acceptée : 119 (60 %) ; statuts : ok 119, card_occluded 53, card_too_oblique 14, card_not_found 9, card_too_small 4, card_wrong_size 1
- Dans le domaine annoncé (inclinaison ≤ 40°, carte ≥ 3,2 px/mm) : 114/164 acceptées (70 %)

Erreur d'échelle relative au centre de la fissure (pire direction) :

- Carte bancaire (ID-1, épaisseur corrigée) : médiane 0.60 %, P90 2.49 %, P95 3.92 %, max 9.15 % (n=119)
- même chose sans correction d'épaisseur : médiane 0.81 %, P90 2.43 %, P95 4.22 %, max 8.78 % (n=119)
- Carte ChArUco imprimée, mêmes scènes : médiane 0.04 %, P90 0.11 %, P95 0.15 %, max 0.26 % (n=119)
- Carte bancaire, au centre de la carte : médiane 0.37 %, P90 0.85 %, P95 0.96 %, max 1.33 % (n=119)
- Biais moyen (moyenne des deux valeurs singulières − 1) : 0.01 % ± 1.30 %
- Incertitude annoncée (1 σ) : médiane 1.91 % ; erreur ≤ 2 σ dans 99 % des cas, ≤ 3 σ dans 99 %

| Doigt | scènes | acceptées | erreur médiane | P90 | bord reconstruit | refus « card_occluded » |
|---|---|---|---|---|---|---|
| none | 91 | 59 | 0.50 % | 1.41 % | 0 | 17 |
| short_mid | 19 | 12 | 1.22 % | 4.34 % | 0 | 6 |
| long_mid | 12 | 10 | 0.32 % | 0.92 % | 0 | 1 |
| corner | 20 | 18 | 0.71 % | 2.99 % | 0 | 1 |
| short_full | 17 | 0 | — | — | 0 | 14 |
| press_centre | 17 | 12 | 1.04 % | 2.71 % | 0 | 3 |
| hand_long | 24 | 8 | 0.79 % | 4.67 % | 2 | 11 |

| Inclinaison | acceptées | erreur médiane carte | P90 | erreur médiane ChArUco |
|---|---|---|---|---|
| 0–15° | 44 | 0.49 % | 1.76 % | 0.03 % |
| 15–30° | 51 | 0.63 % | 2.56 % | 0.03 % |
| 30–41° | 24 | 0.62 % | 2.75 % | 0.05 % |
| 41–60° | 0 | — | — | — |

- Flou estimé sur les bords de la carte vs vrai : erreur médiane +0.10 px, MAE 0.19 px
- Temps de détection : médiane 5.86 s, P95 13.70 s
