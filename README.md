# CrashCase AI

Car damage claims, assessed from photos and priced against similar past claims.

A customer uploads photos of a damaged car. CrashCase finds each damaged area, measures how much of the part it covers, looks up visually similar claims that were already paid, and prices the damage from that evidence. An adjuster sees every estimate next to the past claims behind it, approves or declines, and each approval becomes evidence for the next claim.

![Claim assessment: photo with numbered damage outlines, estimate range, and the past claims each price is based on](docs/screenshots/claimA.png)

Most "car damage AI" projects stop at a classifier that says *dent*. That can't justify a price. CrashCase is a **visual retrieval-augmented** system: the price for each dent comes from real past claims that look like it, and the report cites them by reference.

## How a claim is assessed

```mermaid
flowchart LR
    U[Photos] --> Q{Quality gate<br/>blur, light}
    Q -- retake --> U
    Q --> D[Damage + part<br/>segmentation<br/>YOLOv8-seg]
    D --> E[Crop embeddings<br/>CLIP / DINOv2]
    E --> R[(pgvector<br/>past claims)]
    R --> P[Price from<br/>similar claims]
    D --> F[Fraud checks<br/>reused or edited photos]
    P --> L[Claim report<br/>LLM, cites claims]
    F --> L
    L --> A[Adjuster decision]
    A -- approved --> R
```

1. **Quality gate.** Blurry, dark or overexposed photos are sent back before any model runs.
2. **Damage and parts.** Two YOLOv8-seg models find the damage (dent, scratch, crack, glass, lamp, tyre) and the car part. Overlapping their masks gives "dent on front bumper, 18% of the part".
3. **Retrieval.** Each damage crop is embedded and matched against past claims in pgvector, filtered by damage type, part and car category.
4. **Pricing.** Each similar claim's real price is transferred to this case with a parts-and-labour cost model (severity, repair or replace, part, car size), then averaged by visual similarity. With no similar claims, the cost model prices it alone.
5. **Fraud checks.** A 256-bit perceptual hash catches photos reused from earlier claims; EXIF catches photos edited in Photoshop and similar apps.
6. **Report.** An LLM (Llama 3.1 8B on Groq) writes the claim report from the facts only. If it cites a past claim it wasn't given, the report falls back to a template and the failure is scored in Langfuse.
7. **Feedback loop.** Approved claims are added to the index at the adjuster's final price, so estimates improve without retraining.

## The stack

| Layer | Tools |
| --- | --- |
| Cloud | AWS: ECS Fargate, ECR, ALB, RDS Postgres, S3, CloudWatch, Cloud Map |
| Containers | Docker (multi-stage), Docker Compose |
| Infrastructure as code | Terraform |
| CI/CD | GitHub Actions with AWS OIDC, canary deploys with automatic rollback |
| Experiments and registry | MLflow (runs, model registry, `champion` alias) |
| Data versioning | DVC with an S3 remote |
| Pipelines | Prefect: daily drift check, retraining with a promotion gate, re-indexing |
| Serving | FastAPI, Celery + Redis, BentoML detector service |
| Vector search | pgvector |
| Monitoring | Evidently (data drift), Prometheus + Grafana, CloudWatch alarms |
| LLM observability | Langfuse |
| Labelling | Label Studio |
| Frontend | Next.js 15, React 19 |

## Run it locally

You need Docker. Everything works without trained weights: a stub detector stands in until a model is trained, so the full system can be deployed and tested first.

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
| --- | --- |
| App | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| MLflow | http://localhost:5000 |
| Grafana (admin / admin) | http://localhost:3001 |
| Prometheus | http://localhost:9090 |

The claim index seeds itself with about 1,000 synthetic past claims on first start (`CC_AUTO_SEED`).

Optional profiles:

```bash
docker compose --profile mlops up   # Prefect server + flow runner, Label Studio (http://localhost:8081)
docker compose --profile bento up   # detector as a separate BentoML service
```

### Without Docker

```bash
pip install -e ".[dev]"
CC_INLINE_PROCESSING=true uvicorn crashcase.api.main:app --reload   # no Redis or worker needed
cd web && npm install && API_URL=http://localhost:8000 npm run dev
```

## Train the damage model

Accuracy isn't the goal of this project; the pipeline around the model is. A small YOLOv8n-seg trained for 15 epochs is enough.

1. Request [CarDD](https://cardd-ustc.github.io) and put `CarDD_COCO` in `datasets/`. Any COCO-format damage set (for example a Roboflow export) works too.
2. Train on a free Kaggle or Colab GPU, tracked in MLflow and versioned with DVC:

```bash
pip install -e ".[ml,flows]" dvc[s3]
export MLFLOW_TRACKING_URI=http://localhost:5000
dvc repro          # prepare_cardd.py -> train.py, re-running only what changed
```

`training/train.py` logs parameters, metrics, plots and weights to MLflow and registers a new model version. To serve it, set `CC_DETECTOR_BACKEND=yolo` and `CC_DAMAGE_WEIGHTS=models:/crashcase-damage-seg@champion`, and build the image with `INSTALL_ML=true`.

Once real weights exist, rebuild the index from real photo crops so retrieval compares like with like:

```bash
python scripts/seed_claims.py --images datasets/cardd_yolo/images/val --force
```

## MLOps flows (Prefect)

| Flow | When | What it does |
| --- | --- | --- |
| `drift-check` | Daily, 03:00 PKT | Evidently compares recent claims with earlier ones: photo brightness and sharpness, damage severity, model confidence, damage and part mix, cost. Reports are stored and linked from the Operations page. Drift above `CC_DRIFT_SHARE_THRESHOLD` starts retraining. |
| `retrain-damage-model` | On drift, or by hand | `dvc pull` → train → **gate**: the new version becomes `champion` only if it is no worse than the current one (within a tolerance) → triggers the deploy workflow. |
| `reindex-claims` | After the embedder changes | Re-embeds approved claims from their stored photo crops and regenerates the synthetic set, so old and new vectors never mix. |

Human feedback goes through Label Studio:

```bash
python scripts/label_studio.py export        # approved claims, model boxes as pre-annotations
python scripts/label_studio.py import export.json --out datasets/feedback
dvc add datasets/feedback
```

## Deploy to AWS

```mermaid
flowchart LR
    GH[GitHub Actions] -- OIDC --> ECR[(ECR)]
    User --> ALB
    ALB -- ":80" --> Web[web<br/>Next.js]
    Web -- ":8080" --> ALB
    ALB -- "90%" --> Stable[api-stable]
    ALB -- "10%" --> Canary[api-canary]
    Stable & Canary --> Redis[(Redis)]
    Redis --> Worker[worker<br/>Fargate Spot]
    Stable & Canary & Worker --> RDS[(RDS Postgres<br/>pgvector)]
    Stable & Canary & Worker --> S3[(S3 photos)]
```

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # region, your email for the budget alert
terraform init && terraform apply
```

Then in the GitHub repo settings:

1. Add the secret `AWS_DEPLOY_ROLE_ARN` = `terraform output -raw github_deploy_role_arn`.
2. Add the variable `DEPLOY_ENABLED` = `true`.
3. Run the **Deploy** workflow once with *seed* ticked to fill the claim index.

From then on, every push to `main` that passes CI deploys itself:

1. Build both images and push them to ECR.
2. Start the new API version on `api-canary` and send it 10% of API traffic through the load balancer.
3. Watch the canary's 5xx count and p95 latency for 5 minutes.
4. Healthy: promote to `api-stable` and roll out the worker and web app. Unhealthy: send all traffic back to stable, stop the canary, fail the job.

`scripts/deploy/canary.sh` does the work; the bake time and canary share are inputs on the manual run.

### What it costs

The stack is sized for AWS's new-account credits ($100 up front, up to $200). It has no NAT gateway (that alone would be ~$32 a month), runs the worker on Fargate Spot, and uses `db.t4g.micro`. Running around the clock it comes to roughly **$3 a day**: the load balancer, the database, four small Fargate tasks and their public IPv4 addresses. So:

- Train on Kaggle or Colab, never on EC2 GPUs.
- `terraform destroy` when you are not demoing, and `terraform apply` again before the next demo (about 10 minutes).
- Set `budget_email` to get an email when spend passes 80% of the monthly budget (`budget_usd`, default $50).

## Screens

| Claims | Start a claim | Operations |
| --- | --- | --- |
| ![Claims list](docs/screenshots/list.png) | ![Upload photos](docs/screenshots/new.png) | ![Operations and drift](docs/screenshots/ops.png) |

A claim that reused a photo from an earlier claim is flagged before payout:

![Fraud warning on a claim](docs/screenshots/claimC.png)

## Project layout

```
src/crashcase/
  api/          FastAPI: claims, review, images, stats, drift
  worker/       Celery task
  pipeline/     quality gate, detector (stub / YOLO / BentoML), embedder, retrieval,
                costing, fraud, report, orchestration
  monitoring/   Evidently drift checks
  flows/        Prefect flows and their schedules
  labeling.py   Label Studio round trip
  maintenance.py re-indexing
web/            Next.js adjuster app
serving/        BentoML detector service
training/       CarDD conversion and YOLOv8-seg training with MLflow
infra/terraform AWS infrastructure
scripts/        seeding, Label Studio, canary deploy
monitoring/     Prometheus config, Grafana dashboard
configs/        repair cost table, LLM prompt versions, Label Studio config
```

## Tests

```bash
pytest                        # unit and API tests
CC_TEST_PG_URL=postgresql+psycopg2://user:pass@localhost:5432/db pytest   # + pgvector integration
```

CI runs lint, the full test suite against a real pgvector database, the web build, `terraform validate`, and a container smoke test on every push.

## Limits worth knowing

- **Repair costs are synthetic.** No public dataset has them, so the claims database is generated from `configs/cost_table.yaml` (rough Pakistani workshop prices). The pipeline is built so real insurer data can replace it, and approved claims already do.
- **The stub detector is a placeholder.** It returns plausible fake detections so the system can be deployed and tested before a model exists. Visual similarity only means something once real crops are indexed with CLIP or DINOv2.
- **Estimates are drafts.** An adjuster signs off on every claim, and the app is built around that decision.
