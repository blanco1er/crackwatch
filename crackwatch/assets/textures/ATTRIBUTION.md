# Wall texture used by the demo photos

`plastered_wall_diff_crop.jpg` is a centre crop (x 523..3573, y 863..3233) of the 4K diffuse map of
**"Plastered Wall" by Amal Kumar**, Poly Haven: https://polyhaven.com/a/plastered_wall

- Licence: **CC0 1.0** (public domain), https://polyhaven.com/license — no attribution required; credited anyway.
- Source file: https://dl.polyhaven.org/file/ph-assets/Textures/jpg/4k/plastered_wall/plastered_wall_diff_4k.jpg
  (sha256 in `plastered_wall_diff_crop.json`).

Use: `scripts/make_demo_samples.py --texture ...` renders the four demo photos (`web/samples/`) with this
real wall under a *synthetic* crack whose geometry, and therefore ground truth, is known exactly. The
evaluation sets and the published accuracy figures (`eval/`) do not use this texture and are unchanged.
