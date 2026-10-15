"""Register and run all flows with their schedules: python -m crashcase.flows.serve"""

from prefect import serve

from crashcase.flows.drift_flow import drift_check
from crashcase.flows.reindex_flow import reindex_claims
from crashcase.flows.retrain_flow import retrain

if __name__ == "__main__":
    serve(
        drift_check.to_deployment(
            name="daily", cron="0 22 * * *", parameters={"retrain_on_drift": True}
        ),  # 03:00 Pakistan time
        reindex_claims.to_deployment(name="on-demand"),
        retrain.to_deployment(name="on-demand"),
    )
