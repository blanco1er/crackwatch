"""Build and push the arm64 Lambda image WITHOUT Docker: pip downloads the linux/aarch64 wheels, this script
packs one reproducible layer (root-owned, 0644/0755, fixed mtime) and `crane` appends it to the official
AWS Lambda Python 3.12 arm64 base image (pinned by digest), then sets the handler. Same content as deploy/Dockerfile.

  python deploy/build_image.py --repo <account>.dkr.ecr.us-east-1.amazonaws.com/crackwatch --tag v1
Prints the pushed image reference with its digest (used as the CloudFormation ImageUri).
Requires: crane (brew install crane), pip, an authenticated `crane auth login` for the ECR registry.
"""
import argparse
import os
import subprocess
import sys
import tarfile
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
BASE = "public.ecr.aws/lambda/python:3.12-arm64@sha256:9672c8fa29ab0fc33c5b2b22ffe91e99c075d6fc67cc606fcd702a8adee3c5a8"
MTIME = 1760832000  # fixed for reproducible layers
SKIP_DIRS = {"__pycache__", ".pytest_cache"}


def stage(tmp):
    task = os.path.join(tmp, "var", "task")
    os.makedirs(task)
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                    "--platform", "manylinux_2_28_aarch64", "--platform", "manylinux2014_aarch64",
                    "--implementation", "cp", "--python-version", "3.12", "--only-binary=:all:",
                    "--target", task, "-r", os.path.join(ROOT, "deploy", "requirements-lambda.txt")], check=True)
    files = [(os.path.join(ROOT, "deploy", "lambda_handler.py"), "lambda_handler.py")]
    for sub in ("crackwatch", "web"):
        for dp, dns, fns in os.walk(os.path.join(ROOT, sub)):
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            for fn in fns:
                if fn.endswith(".pyc") or fn == ".DS_Store":
                    continue
                src = os.path.join(dp, fn)
                files.append((src, os.path.relpath(src, ROOT)))
    for fn in ("card_A6-5x7-15mm.pdf", "card_A5-7x10-17mm.pdf"):
        files.append((os.path.join(ROOT, "print", fn), os.path.join("print", fn)))
    for src, rel in files:
        dst = os.path.join(task, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as f, open(dst, "wb") as g:
            g.write(f.read())
    return tmp


def make_layer(tmp, out):
    def norm(ti):
        ti.uid = ti.gid = 0
        ti.uname = ti.gname = "root"
        ti.mtime = MTIME
        if ti.isdir():
            ti.mode = 0o755
        elif ti.isfile():
            ti.mode = 0o755 if (ti.mode & 0o111) else 0o644
        return ti

    with tarfile.open(out, "w:gz", compresslevel=6) as tar:
        for dp, dns, fns in os.walk(os.path.join(tmp, "var")):
            dns.sort()
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            rel = os.path.relpath(dp, tmp)
            tar.add(dp, arcname=rel, recursive=False, filter=norm)
            for fn in sorted(fns):
                if fn.endswith(".pyc"):
                    continue
                tar.add(os.path.join(dp, fn), arcname=os.path.join(rel, fn), filter=norm)
    return out


def dry_run(out_dir):
    """Stage + layer only (no registry): python deploy/build_image.py --dry-run <dir>"""
    tmp = tempfile.mkdtemp(prefix="cw-image-", dir=out_dir)
    stage(tmp)
    layer = make_layer(tmp, os.path.join(out_dir, "layer.tar.gz"))
    print(layer, f"{os.path.getsize(layer) / 1e6:.1f} MB")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--dry-run":
        return dry_run(sys.argv[2])
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="cw-image-") as tmp:
        stage(tmp)
        layer = make_layer(tmp, os.path.join(tmp, "layer.tar.gz"))
        print(f"layer: {os.path.getsize(layer) / 1e6:.1f} MB", file=sys.stderr)
        ref = f"{a.repo}:{a.tag}"
        subprocess.run(["crane", "append", "--platform", "linux/arm64", "-b", BASE, "-f", layer, "-t", ref], check=True,
                       stdout=subprocess.DEVNULL)
        out = subprocess.run(["crane", "mutate", ref, "--cmd", "lambda_handler.handler", "-t", ref],
                             check=True, capture_output=True, text=True).stdout.strip()
        print(out)


if __name__ == "__main__":
    main()
