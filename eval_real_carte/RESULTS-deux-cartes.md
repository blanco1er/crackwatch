# Carte bancaire et carte imprimée sur la même photo (vraies photos)

Généré par `scripts/eval_idcard_twocards.py` le 2026-10-24 17:40 ; photos réduites à 4032 px comme le service ; focale lue dans l'EXIF. La carte imprimée (ChArUco) sert de référence.

- Photos : 13 ; carte bancaire acceptée : 13 ; fissure mesurée par les deux : 13
- **Largeur aux mêmes points de la fissure**, carte / ChArUco : médiane -1.9 %, de -3.1 à +1.3 % ; dans ±2 σ d'échelle annoncés : 13/13
- La « fissure principale » de chaque mesure couvre une portion différente de la photo (fenêtre redressée autour de chaque carte) : sa médiane n'est pas comparable d'une référence à l'autre ; la ligne ci-dessus l'est.
- Écart de largeur médiane carte / ChArUco : médiane +21.4 % ; dans ±2 incertitudes annoncées : 1/13

| Dossier | Photo | ChArUco méd. / max (± mm) | Carte méd. / max (± mm) | écart méd. | mêmes points (%) | échelle à la fissure (%) | ± échelle annoncé (%) | carte devant le plan ChArUco (mm) | angle des plans (°) | statut carte |
|---|---|---|---|---|---|---|---|---|---|---|
| beton-deux-cartes | IMG_1641.heic | 4.75 / 5.83 (± 0.11) | 4.22 / 5.21 (± 0.12) | -11.0 % | 0.84 | [0.81, 2.14] | 3.24 | -6.0 | 2.7 | ok |
| beton-deux-cartes | IMG_1642.heic | 4.50 / 6.29 (± 0.15) | 3.81 / 4.81 (± 0.12) | -15.2 % | 0.6 | [0.25, 0.94] | 2.25 | -3.0 | 1.1 | ok |
| beton-deux-cartes | IMG_1644.heic | 5.08 / 6.24 (± 0.13) | 4.38 / 5.14 (± 0.13) | -13.8 % | 0.9 | [2.58, 3.23] | 1.61 | -2.5 | 3.8 | ok |
| beton-deux-cartes | IMG_1645.heic | 4.87 / 5.86 (± 0.12) | 4.38 / 5.03 (± 0.14) | -10.1 % | 0.13 | [1.74, 2.41] | 1.74 | -5.5 | 2.9 | ok |
| beton-deux-cartes | IMG_1646.heic | 5.04 / 5.85 (± 0.10) | 4.46 / 5.18 (± 0.12) | -11.4 % | 1.34 | [-0.58, 0.94] | 1.9 | -1.8 | 2.3 | ok |
| enduit-deux-cartes | IMG_1631.heic | 4.11 / 7.72 (± 0.14) | 3.92 / 7.15 (± 0.11) | -4.6 % | -0.73 | [1.32, 2.46] | 2.0 | -20.7 | 6.7 | ok |
| enduit-deux-cartes | IMG_1632.heic | 3.82 / 8.06 (± 0.13) | 6.72 / 8.18 (± 0.14) | 76.0 % | -2.67 | [0.12, 1.62] | 1.49 | -14.9 | 5.4 | ok |
| enduit-deux-cartes | IMG_1633.heic | 4.66 / 8.36 (± 0.12) | 6.93 / 8.20 (± 0.13) | 48.8 % | -2.51 | [1.28, 2.57] | 1.86 | -13.9 | 6.0 | ok |
| enduit-deux-cartes | IMG_1634.heic | 4.97 / 8.15 (± 0.12) | 6.69 / 8.18 (± 0.14) | 34.5 % | -2.67 | [1.86, 4.45] | 2.1 | -15.7 | 7.8 | ok |
| enduit-deux-cartes | IMG_1635.heic | 4.13 / 8.03 (± 0.12) | 6.71 / 8.06 (± 0.14) | 62.6 % | -1.92 | [1.74, 4.24] | 2.09 | -15.1 | 7.4 | ok |
| enduit-deux-cartes | IMG_1636.heic | 5.35 / 9.82 (± 0.12) | 6.50 / 9.17 (± 0.17) | 21.4 % | -2.62 | [2.43, 6.41] | 2.89 | -17.5 | 8.3 | ok |
| enduit-deux-cartes | IMG_1637.heic | 4.28 / 8.27 (± 0.12) | 5.73 / 8.28 (± 0.14) | 33.9 % | -3.15 | [1.18, 4.92] | 2.92 | -21.1 | 7.9 | ok |
| enduit-deux-cartes | IMG_1638.heic | 4.32 / 8.17 (± 0.14) | 6.49 / 8.74 (± 0.17) | 50.1 % | -1.86 | [0.52, 2.64] | 2.42 | -18.1 | 6.8 | ok |
