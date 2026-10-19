# CrackWatch

A digital crack gauge. A printed ChArUco card, taped once next to a crack, turns every phone photo into a
**metric, rectified and re-registrable** view of the wall. OpenCV 5 measures the crack width in millimetres
with an uncertainty and tracks its change between visits. An agent (Amazon Nova 2 Lite on Amazon Bedrock,
validated by a deterministic policy) decides what happens next: a retake, a **closer photo of a precise
region**, a comparison with the previous visit, or a maintenance ticket that **always waits for a human**.

> CrackWatch is a monitoring and triage aid. It is **not** a structural diagnosis and does not replace a
> structural engineer. Thresholds in `crackwatch/agent.py` are configurable defaults, not engineering norms.

Entry for the OpenCV AI Competition 2026 (AWS). Hosted demo: **DEMO_URL** (guided 4-step inspection on
synthetic photos with known ground truth, or your own photo with the printed card).

![Architecture](docs/architecture.png)

## How it works

| Stage | OpenCV 5.0.0 | Notes |
|---|---|---|
| Scale | `cv2.aruco.CharucoDetector.detectBoard`, `CharucoBoard.matchImagePoints`, `cv2.findHomography(USAC_MAGSAC)` | Board frame in millimetres; A6 card (5×7 squares of 15 mm) or A5 card |
| Quality | Sobel on the card's step edges, saturation outside the card, tilt from the homography | Blur measured **in pixels** (Gaussian σ) on the card itself |
| Rectification | `cv2.warpPerspective` into the card frame | Resolution chosen from the native px/mm |
| Segmentation | 8-bit median background, multi-scale Hessian ridge (`GaussianBlur` + `Sobel`), hysteresis with `connectedComponentsWithStats`, shape filters, Zhang–Suen thinning | `cv2.ximgproc` is contrib-only in OpenCV 5, so thinning is implemented in NumPy |
| Width | Perpendicular profiles (`cv2.remap`, 0.25 px steps), each **deconvolved with the blur measured on the card** (box ⊗ Gaussian model) | Output: median / P90 / sustained max (P95 over 6 mm), 1σ uncertainty, confidence, minimum measurable width |
| Change | Same card frame, or ORB + `findHomography(USAC_MAGSAC)` + `findTransformECC` (band-passed) if the card was re-glued | Widening and new length; a segment is "new" only if visit 1 shows no ridge there |
| Decision | Tool use through the Bedrock Converse API; rule policy as validator and fallback | Every step traced (tool, reason, model, latency, tokens, cost) |

![Agent flow](docs/agent-flow.png)

The card does four jobs at once: metric scale, rectification, registration between visits, and measurement
of the camera's blur (point-spread function), which is what makes sub-pixel widths possible.

## Results

All numbers below are produced by scripts in this repository. **Synthetic** and **real** results are kept apart.

### Synthetic (held-out set: seeds 20000+, never used for tuning; 300 single photos, 40 two-visit pairs)

Procedural concrete, cracks of 0.2–5 mm, 3–9 px/mm, tilt 0–45°, blur, JPEG, glare, motion blur, stains and joints.
Full tables and the list of all 92 failure cases: [`eval/RESULTS.md`](eval/RESULTS.md).

| Metric (E1) | Value |
|---|---|
| Card detected | 299/300 (99.7 %) |
| Crack detected (≥ 10 matched points) | 259/300 (86.3 %); 30 of the 41 misses are cracks < 0.5 mm |
| Point-wise width MAE | **0.21 mm** (median absolute error 0.10 mm) |
| Same, pixel-level distance-transform baseline | 0.44 mm |
| Per-image median-width MAE | **0.17 mm** |
| Per-image sustained max-width MAE | 0.37 mm (bias +0.27 mm: over-estimation) |
| Announced uncertainty covers the error (≤ 2σ) | 71 % of images (under-estimated) |

| Metric (E4, two visits) | Value |
|---|---|
| Registration error, card left in place / card re-glued | 0.00 / 0.04 mm (median) |
| Widening MAE (true widening 0–1 mm) | **0.07 mm** |
| Change alert precision / recall; false alerts on unchanged pairs | 1.00 / 0.94; 0/8 |

On the tuning set (seeds 1000–1299) the median-width MAE was 0.10 mm and the max-width MAE 0.27 mm: the
generalisation gap is reported, not hidden. The evaluation was re-run from scratch on 19 Oct 2026 and
reproduced the same numbers.

### Real photos

Printed test chart (8 bars of known width, 0.2–3 mm) photographed at 3 distances × 3 angles × 2 lightings, its
"second visit" version (3 bars widened, 2 extended), and two real cracks (repeatability):
**REAL_RESULTS** — produced by `scripts/process_real.py`, see `eval_real/RESULTS.md`.

### Failure cases (shown, not hidden)

- A thin crack over a dark stain, or a crack folding back on itself: width over-estimated.
- Cracks under ~2 px wide in the photo are often missed: the agent asks for a closer photo instead of
  reporting a number.
- Long straight dark lines (tile joints) are filtered by shape and can hide a real straight crack.
- The homography assumes a planar wall around the card; curved surfaces are out of scope.
- An experimental spur-pruning step (`SegParams.prune_short_mm`, off by default) improved the max-width error
  on the tuning set (0.266 → 0.251 mm) but lowered crack coverage (0.85 → 0.75), so it was not adopted.

## Hosted demo and AWS

- **One container Lambda, arm64 (Graviton)**, Python 3.12, `opencv-python-headless==5.0.0.93`, 3008 MB, behind an
  **API Gateway HTTP API** with throttled routes. It serves the page and runs measurement + agent loop.
- **Amazon S3** (private, SSE, TLS only): photos are uploaded with a 5-minute presigned POST (JPEG, ≤ 15 MB) and
  **deleted after 1 day**. Decoding drops EXIF and GPS.
- **Amazon Bedrock**: `us.amazon.nova-2-lite-v1:0` through the Converse API with 5 tools. On-demand price read from
  the AWS Price List API on 19 Oct 2026: $0.33 / $2.75 per million input / output tokens in us-east-1, i.e.
  about $0.0015 per decision.
- **DynamoDB**: traces, tickets, usage counters and the anonymous visit log (TTL). **CloudWatch**: JSON logs, 14 days.
- **Cost guards**: route throttling, inspections per day (global and per anonymous visitor), LLM calls per day
  (beyond it, the rules decide alone), 15 MB photo limit, 29 s timeout. Data resources are retained if the stack is deleted.
- **Least privilege**: the function role can read/write `uploads/*` in its bucket, four DynamoDB actions on its table,
  and `bedrock:InvokeModel` on one model. No key or secret is stored in the image or in this repository.
- **Privacy**: visits are logged anonymously (salted hash of IP + browser; the IP itself is never stored) so the author
  knows whether the demo was tried. No photo content, file name or personal data is logged.

## Reproduce

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python tests/test_agent.py && .venv/bin/python tests/test_api.py      # fast tests
.venv/bin/python scripts/cw.py cards --out print                                 # printable cards + test charts
.venv/bin/python scripts/make_synth.py --out data/synth_test --n 300 --pairs 40 --seed0 20000
.venv/bin/python scripts/run_eval.py --data data/synth_test --out eval           # E1 + E4 -> eval/RESULTS.md
.venv/bin/python scripts/cw.py agent photo.jpg --previous older.jpg              # one inspection, rules only
.venv/bin/python scripts/serve_local.py --port 8765                              # the demo page, locally, rules only
AWS_PROFILE=<profile> .venv/bin/python scripts/serve_local.py --bedrock         # ... with Nova 2 Lite as planner
.venv/bin/python scripts/process_real.py --dir <photos> --out eval_real          # real-photo evaluation
```

Deploy (us-east-1, your own credentials; needs the AWS CLI and `crane`, not Docker):

```bash
AWS_PROFILE=<profile> deploy/deploy.sh
```

`deploy/build_image.py` installs the linux/aarch64 wheels with `pip --platform`, packs one reproducible layer and
appends it with `crane` to the official `public.ecr.aws/lambda/python:3.12-arm64` image, pinned by digest.
`deploy/Dockerfile` builds the same image with Docker. `deploy/template.yaml` is a CloudFormation template using the
SAM transform, deployed with plain `aws cloudformation deploy`.

Print the cards from `print/*.pdf` at **100 % / actual size** and check the printed 50 mm ruler with a real ruler.

## Layout

| Path | Content |
|---|---|
| `crackwatch/card.py`, `printio.py` | ChArUco card specs, print-exact PNG/PDF, E2/E4 test charts |
| `crackwatch/measure.py` | measurement pipeline |
| `crackwatch/change.py` | two-visit registration and change |
| `crackwatch/agent.py` | rule policy, Nova (Converse) planner, guard-rails, agent loop and trace |
| `crackwatch/service.py`, `api.py`, `store.py`, `visits.py` | hosted demo: inspection service, routes, storage, anonymous visits |
| `crackwatch/synth.py`, `evaluate.py`, `scripts/run_eval.py`, `eval_e4.py` | synthetic generator and evaluation |
| `scripts/process_real.py` | real-photo evaluation (E2, E4 real, E3) |
| `scripts/make_demo_samples.py` | the 4 synthetic demo photos (one illustrative wall, ground truth shown in the UI) |
| `web/` | demo page (no framework, no third-party request) |
| `deploy/` | Lambda handler, image build without Docker, Dockerfile, CloudFormation template, deploy script |
| `tests/` | agent scenarios, API, cost guards, visits, planner fallback |

The four demo photos are one illustrative wall chosen among six generated walls; the aggregate numbers above are
the honest measure of accuracy, and the demo page shows each photo's ground truth next to the measurement.

## License

MIT — see `LICENSE`. Author: Blanco (@blanco_1er).
