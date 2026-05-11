# seed_runs

Empty placeholder so the Dockerfile's `COPY dashboard/backend/seed_runs/ ...`
resolves when building locally from the source repo.

Real rollouts are populated by `deploy_to_hf_space.sh` into the **Space repo's**
copy of this directory, not here. The source repo intentionally stays clean —
`environments/teachingbench/outputs/runs/` is where local runs accumulate.

If you want a local docker build to have seed rollouts too, copy from
`../../../environments/teachingbench/outputs/runs/` into this directory before
running `docker build`.
