# Apptainer / ARC

ARC does not run Docker, so we use Apptainer instead.

Simple idea:

```text
Docker image  -> not allowed on ARC
.sif image    -> Apptainer can run this on ARC
```

## 1. What we need once

We need one `.sif` image per repo + Unity version.

Name it like this:

```text
swegb-<repo>-<unity-version>.sif
```

Example:

```text
swegb-fungus-2019.4.36f1.sif
```

Put images somewhere like:

```text
/scratch/$USER/swegb-images/
```

The image should basically contain what the Docker image had:

```text
Unity editor
git / git-lfs / xvfb
Python + SWE-agent
the repo cache if we baked one in
```

## 2. Set the ARC job environment

```bash
# we load Apptainer on ARC
module load apptainer

# we tell swe-game-bench to use Apptainer, not Docker
export SWE_GAME_BENCH_BACKEND=apptainer

# we tell it where the .sif images are
export SWE_GAME_BENCH_APPTAINER_IMAGE_DIR=/scratch/$USER/swegb-images

# we point Unity to the license folder
export LICENSE_PATH=/scratch/$USER/unity_license_data

# we keep outputs on scratch, not home
export SWE_GAME_BENCH_RUNS=/scratch/$USER/swe-game-bench-runs
```

## 3. Check which image it expects

```bash
swe-game-bench apptainer image --repo fungus --bucket 2019.4.36f1
```

That should print something like:

```text
/scratch/$USER/swegb-images/swegb-fungus-2019.4.36f1.sif
```

If that file does not exist, the run will stop and tell us the image is missing.

## 4. Run one instance

```bash
# we run pass@10 for one issue
swe-game-bench pass-at-k --instances fungus-879 --k 10
```

## 5. Run a group into a named folder

```bash
# we keep this batch in its own result folder
swe-game-bench pass-at-k \
  --instances fungus-867,fungus-879,fungus-922,fungus-945 \
  --k 10 \
  --runs-root /scratch/$USER/swe-game-bench-runs/passk/gpt-5.2_t0.8/fungus-2019_4
```

## 6. What the backend does for us

It runs roughly:

```text
apptainer exec image.sif swe-game-bench generate/evaluate/validate
```

And it mounts:

```text
this repo       -> /pipeline
runs folder     -> /pipeline/runs
license folder  -> /usr/share/unity3d/Unity
temp dirs       -> /tmp and /root
```

So the benchmark code can keep using the same `/pipeline/...` paths as Docker.
