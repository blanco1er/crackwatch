# Carte bancaire comme référence d'échelle — évaluation synthétique

Généré par `scripts/eval_idcard.py` le 2026-10-24 01:40, OpenCV 5.0.0, graines 50000–50199.
Mode EXIF : la vraie focale est donnée au détecteur (comme si l'app envoyait FocalLengthIn35mmFilm).

- Scènes : 200 ; carte acceptée : 134 (67 %) ; statuts : ok 134, card_occluded 25, card_too_oblique 17, card_wrong_size 9, card_not_found 7, card_too_small 5, card_not_flat 2, card_cut_by_frame 1
- Dans le domaine annoncé (inclinaison ≤ 40°, carte ≥ 3,2 px/mm) : 130/164 acceptées (79 %)

Erreur d'échelle relative au centre de la fissure (pire direction) :

- Carte bancaire (ID-1, épaisseur corrigée) : médiane 0.48 %, P90 1.41 %, P95 1.70 %, max 15.42 % (n=134)
- même chose sans correction d'épaisseur : médiane 0.71 %, P90 1.51 %, P95 1.92 %, max 15.09 % (n=134)
- Carte ChArUco imprimée, mêmes scènes : médiane 0.03 %, P90 0.09 %, P95 0.11 %, max 0.36 % (n=133)
- Carte bancaire, au centre de la carte : médiane 0.39 %, P90 0.86 %, P95 0.99 %, max 16.41 % (n=134)
- Biais moyen (moyenne des deux valeurs singulières − 1) : -0.08 % ± 1.37 %
- Incertitude annoncée (1 σ) : médiane 0.94 % ; erreur ≤ 2 σ dans 99 % des cas, ≤ 3 σ dans 99 %

| Doigt | scènes | acceptées | erreur médiane | P90 | bord reconstruit | refus « card_occluded » |
|---|---|---|---|---|---|---|
| none | 120 | 88 | 0.47 % | 1.13 % | 1 | 7 |
| short_mid | 26 | 21 | 0.37 % | 0.96 % | 0 | 5 |
| long_mid | 10 | 7 | 0.58 % | 1.14 % | 0 | 1 |
| corner | 20 | 16 | 0.65 % | 1.55 % | 0 | 0 |
| short_full | 24 | 2 | 9.74 % | 14.29 % | 1 | 12 |

| Inclinaison | acceptées | erreur médiane carte | P90 | erreur médiane ChArUco |
|---|---|---|---|---|
| 0–15° | 46 | 0.53 % | 1.71 % | 0.03 % |
| 15–30° | 55 | 0.37 % | 1.11 % | 0.04 % |
| 30–41° | 33 | 0.51 % | 0.98 % | 0.04 % |
| 41–60° | 0 | — | — | — |

- Flou estimé sur les bords de la carte vs vrai : erreur médiane +0.13 px, MAE 0.20 px
- Temps de détection : médiane 2.05 s, P95 6.14 s
