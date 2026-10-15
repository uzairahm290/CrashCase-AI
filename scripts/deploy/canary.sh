#!/usr/bin/env bash
# Canary deploy of a new API image on ECS, then roll the rest of the stack.
#
#   1. Start the new API version on the "api-canary" service.
#   2. Send CANARY_PERCENT of API traffic to it through the ALB listener weights.
#   3. Bake for BAKE_SECONDS, watching the canary's 5xx count and p95 latency.
#   4. Healthy -> promote (stable gets the new version, weights back to 100/0, canary off).
#      Unhealthy -> roll back (weights 100/0, canary off) and fail the job.
#   5. Roll the worker and the web app to the new images.
#
# Needs: aws CLI v2, jq. Env: NAME, API_IMAGE, WEB_IMAGE, optional CANARY_PERCENT,
# BAKE_SECONDS, MAX_5XX, MAX_P95_SECONDS, CHECK_INTERVAL.
set -euo pipefail

NAME=${NAME:-crashcase}
CLUSTER=${CLUSTER:-$NAME}
CANARY_PERCENT=${CANARY_PERCENT:-10}
BAKE_SECONDS=${BAKE_SECONDS:-300}
MAX_5XX=${MAX_5XX:-5}
MAX_P95_SECONDS=${MAX_P95_SECONDS:-3}
CHECK_INTERVAL=${CHECK_INTERVAL:-30}
: "${API_IMAGE:?set API_IMAGE}" "${WEB_IMAGE:?set WEB_IMAGE}"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# --- Look up the load balancer pieces by name (no ARNs hard-coded in CI) ---------------
LB_ARN=$(aws elbv2 describe-load-balancers --names "$NAME" --query 'LoadBalancers[0].LoadBalancerArn' --output text)
LB_SUFFIX=${LB_ARN#*:loadbalancer/}
LISTENER_ARN=$(aws elbv2 describe-listeners --load-balancer-arn "$LB_ARN" \
  --query 'Listeners[?Port==`8080`].ListenerArn | [0]' --output text)
TG_STABLE=$(aws elbv2 describe-target-groups --names "$NAME-api-stable" --query 'TargetGroups[0].TargetGroupArn' --output text)
TG_CANARY=$(aws elbv2 describe-target-groups --names "$NAME-api-canary" --query 'TargetGroups[0].TargetGroupArn' --output text)
# CloudWatch dimension format: "targetgroup/<name>/<id>"
TG_CANARY_SUFFIX="targetgroup/${TG_CANARY#*:targetgroup/}"

set_weights() { # stable% canary%
  aws elbv2 modify-listener --listener-arn "$LISTENER_ARN" --default-actions "$(jq -nc \
    --arg s "$TG_STABLE" --arg c "$TG_CANARY" --argjson ws "$1" --argjson wc "$2" \
    '[{Type:"forward",ForwardConfig:{TargetGroups:[{TargetGroupArn:$s,Weight:$ws},{TargetGroupArn:$c,Weight:$wc}]}}]')" >/dev/null
  log "traffic: stable $1% / canary $2%"
}

# Copy the current task definition, swap the image, register it, print the new ARN.
new_task_def() { # family container image
  aws ecs describe-task-definition --task-definition "$1" --query taskDefinition --output json |
    jq --arg c "$2" --arg img "$3" '
      .containerDefinitions |= map(if .name == $c then .image = $img else . end)
      | del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities,
            .registeredAt, .registeredBy, .deregisteredAt)' >/tmp/td.json
  aws ecs register-task-definition --cli-input-json file:///tmp/td.json \
    --query taskDefinition.taskDefinitionArn --output text
}

deploy() { # service task_def [desired]
  local args=(--cluster "$CLUSTER" --service "$1" --task-definition "$2")
  [ -n "${3:-}" ] && args+=(--desired-count "$3")
  aws ecs update-service "${args[@]}" >/dev/null
  log "updating $1 -> ${2##*/}"
  aws ecs wait services-stable --cluster "$CLUSTER" --services "$1"
  log "$1 is stable"
}

metric() { # name stat-or-extended period-seconds
  local stat_args=(--statistics Sum)
  [ "$2" = "p95" ] && stat_args=(--extended-statistics p95)
  aws cloudwatch get-metric-statistics --namespace AWS/ApplicationELB --metric-name "$1" \
    --dimensions Name=LoadBalancer,Value="$LB_SUFFIX" Name=TargetGroup,Value="$TG_CANARY_SUFFIX" \
    --start-time "$(date -u -d "-$3 seconds" +%Y-%m-%dT%H:%M:%SZ)" --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --period "$3" "${stat_args[@]}" --output json |
    jq -r 'if (.Datapoints|length)==0 then 0 else (.Datapoints[0].Sum // .Datapoints[0].ExtendedStatistics.p95 // 0) end'
}

rollback() {
  log "ROLLBACK: $1"
  set_weights 100 0
  aws ecs update-service --cluster "$CLUSTER" --service api-canary --desired-count 0 >/dev/null
  echo "::error::Canary rolled back: $1"
  exit 1
}

# --- 1-2. Canary --------------------------------------------------------------------------
API_TD=$(new_task_def "$NAME-api" api "$API_IMAGE")
deploy api-canary "$API_TD" 1 || rollback "canary tasks never became stable"
set_weights $((100 - CANARY_PERCENT)) "$CANARY_PERCENT"

# --- 3. Bake ------------------------------------------------------------------------------
elapsed=0
while [ "$elapsed" -lt "$BAKE_SECONDS" ]; do
  sleep "$CHECK_INTERVAL"
  elapsed=$((elapsed + CHECK_INTERVAL))
  errors=$(metric HTTPCode_Target_5XX_Count Sum "$elapsed")
  p95=$(metric TargetResponseTime p95 "$elapsed")
  log "bake ${elapsed}s/${BAKE_SECONDS}s: canary 5xx=$errors p95=${p95}s"
  if awk "BEGIN{exit !($errors > $MAX_5XX)}"; then rollback "$errors server errors on the canary"; fi
  if awk "BEGIN{exit !($p95 > $MAX_P95_SECONDS)}"; then rollback "p95 latency ${p95}s on the canary"; fi
done

# --- 4. Promote ---------------------------------------------------------------------------
deploy api-stable "$API_TD"
set_weights 100 0
aws ecs update-service --cluster "$CLUSTER" --service api-canary --desired-count 0 >/dev/null
log "canary promoted to stable"

# --- 5. Worker and web ----------------------------------------------------------------------
deploy worker "$(new_task_def "$NAME-worker" worker "$API_IMAGE")"
deploy web "$(new_task_def "$NAME-web" web "$WEB_IMAGE")"
log "deploy complete"
