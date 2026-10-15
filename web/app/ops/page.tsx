import OpsView from "./OpsView";

export const dynamic = "force-dynamic";

// Server component so tool links come from runtime env, not the build.
export default function OpsPage() {
  const links = [
    { name: "Grafana", url: process.env.GRAFANA_URL, what: "Latency, throughput and pipeline dashboards" },
    { name: "MLflow", url: process.env.MLFLOW_URL, what: "Training runs and the model registry" },
    { name: "Prometheus", url: process.env.PROMETHEUS_URL, what: "Raw metrics and alerts" },
    { name: "Langfuse", url: process.env.LANGFUSE_URL, what: "Report prompts, cost and quality" },
    { name: "API docs", url: process.env.API_DOCS_URL, what: "Every endpoint, try it live" },
  ].filter((l): l is { name: string; url: string; what: string } => Boolean(l.url));
  return <OpsView links={links} />;
}
