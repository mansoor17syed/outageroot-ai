#!/usr/bin/env bash
set -euo pipefail

PUSHGATEWAY_URL="${PUSHGATEWAY_URL:-http://localhost:9091}"
SERVICE_NAME="${SERVICE_NAME:-checkout}"
JOB_NAME="${JOB_NAME:-outageroot-sim}"
ITERATIONS="${ITERATIONS:-20}"
SLEEP_SECONDS="${SLEEP_SECONDS:-1}"

echo "Sending synthetic incident metrics to ${PUSHGATEWAY_URL}"
echo "job=${JOB_NAME}, service=${SERVICE_NAME}, iterations=${ITERATIONS}"

for i in $(seq 1 "${ITERATIONS}"); do
  # Deterministic but changing signal shape for demo purposes.
  error_rate=$(( (i % 5) + 1 ))
  latency_ms=$(( 120 + (i * 17) % 250 ))
  cpu_burst=$(( 40 + (i * 13) % 55 ))

  cat <<EOF | curl -sS --data-binary @- "${PUSHGATEWAY_URL}/metrics/job/${JOB_NAME}/service/${SERVICE_NAME}" >/dev/null
# TYPE outageroot_error_rate gauge
outageroot_error_rate{service="${SERVICE_NAME}"} ${error_rate}
# TYPE outageroot_latency_ms gauge
outageroot_latency_ms{service="${SERVICE_NAME}"} ${latency_ms}
# TYPE outageroot_cpu_burst gauge
outageroot_cpu_burst{service="${SERVICE_NAME}"} ${cpu_burst}
EOF

  echo "Pushed sample ${i}: error_rate=${error_rate}, latency_ms=${latency_ms}, cpu_burst=${cpu_burst}"
  sleep "${SLEEP_SECONDS}"
done

echo "Done. Query in Prometheus:"
echo "  outageroot_error_rate"
echo "  outageroot_latency_ms"
echo "  outageroot_cpu_burst"
