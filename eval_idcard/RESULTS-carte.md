# Carte bancaire comme référence d'échelle — évaluation synthétique

Généré par `scripts/eval_idcard.py` le 2026-10-24 01:31, OpenCV 5.0.0, graines 50000–50199.

- Scènes : 200 ; carte acceptée : 132 (66 %) ; statuts : ok 132, card_occluded 27, card_too_oblique 16, card_wrong_size 9, card_not_found 7, card_too_small 5, card_not_flat 3, card_cut_by_frame 1
- Dans le domaine annoncé (inclinaison ≤ 40°, carte ≥ 3,2 px/mm) : 128/164 acceptées (78 %)

Erreur d'échelle relative au centre de la fissure (pire direction) :

- Carte bancaire (ID-1, épaisseur corrigée) : médiane 0.77 %, P90 2.47 %, P95 3.59 %, max 7.43 % (n=132)
- même chose sans correction d'épaisseur : médiane 0.83 %, P90 2.52 %, P95 3.67 %, max 7.04 % (n=132)
- Carte ChArUco imprimée, mêmes scènes : médiane 0.03 %, P90 0.10 %, P95 0.11 %, max 0.36 % (n=131)
- Carte bancaire, au centre de la carte : médiane 0.40 %, P90 0.86 %, P95 0.97 %, max 5.95 % (n=132)
- Biais moyen (moyenne des deux valeurs singulières − 1) : -0.11 % ± 1.14 %
- Incertitude annoncée (1 σ) : médiane 0.94 % ; erreur ≤ 2 σ dans 95 % des cas, ≤ 3 σ dans 99 %

| Doigt | scènes | acceptées | erreur médiane | P90 | bord reconstruit | refus « card_occluded » |
|---|---|---|---|---|---|---|
| none | 120 | 88 | 0.74 % | 2.60 % | 1 | 7 |
| short_mid | 26 | 21 | 0.77 % | 3.51 % | 0 | 5 |
| long_mid | 10 | 7 | 0.95 % | 1.22 % | 0 | 1 |
| corner | 20 | 15 | 0.88 % | 1.49 % | 0 | 0 |
| short_full | 24 | 1 | 3.27 % | 3.27 % | 0 | 14 |

| Inclinaison | acceptées | erreur médiane carte | P90 | erreur médiane ChArUco |
|---|---|---|---|---|
| 0–15° | 45 | 0.76 % | 1.96 % | 0.03 % |
| 15–30° | 54 | 0.79 % | 3.10 % | 0.04 % |
| 30–41° | 33 | 0.77 % | 1.68 % | 0.04 % |
| 41–60° | 0 | — | — | — |

- Flou estimé sur les bords de la carte vs vrai : erreur médiane +0.14 px, MAE 0.20 px
- Temps de détection : médiane 2.59 s, P95 7.44 s
