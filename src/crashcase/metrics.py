from prometheus_client import Counter, Histogram

CLAIMS_PROCESSED = Counter("crashcase_claims_processed_total", "Claims processed", ["status"])
PIPELINE_SECONDS = Histogram(
    "crashcase_pipeline_seconds",
    "End-to-end claim pipeline time",
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
STAGE_SECONDS = Histogram("crashcase_stage_seconds", "Time per pipeline stage", ["stage"])
DETECTIONS = Counter("crashcase_detections_total", "Damage detections", ["damage_type"])
FRAUD_FLAGS = Counter("crashcase_fraud_flags_total", "Claims flagged for possible fraud")
RETRIEVAL_HITS = Histogram(
    "crashcase_retrieval_similarity",
    "Top-1 similarity of retrieved past claims",
    buckets=(0.1, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0),
)
REPORTS = Counter("crashcase_reports_total", "Reports generated", ["generator"])
