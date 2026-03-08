#!/usr/bin/env bash
set -euo pipefail

NS="${NS:-monitoring}"
PROM_CONFIGMAP="${PROM_CONFIGMAP:-prom-config}"
PROM_DEPLOYMENT="${PROM_DEPLOYMENT:-prom}"

echo "Applying scrape config to ${NS}/${PROM_CONFIGMAP} ..."
kubectl apply -n "${NS}" -f - <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: prom-config
  namespace: monitoring
data:
  prometheus.yml: |
    global:
      scrape_interval: 15s
    scrape_configs:
      - job_name: prometheus
        static_configs:
          - targets: ['localhost:9090']
      - job_name: pushgateway
        static_configs:
          - targets: ['pushgateway.monitoring.svc.cluster.local:9091']
      - job_name: node-exporter-lite
        static_configs:
          - targets: ['node-exporter-lite.monitoring.svc.cluster.local:9100']
EOF

echo "Restarting deployment ${NS}/${PROM_DEPLOYMENT} ..."
kubectl rollout restart deploy/"${PROM_DEPLOYMENT}" -n "${NS}"
kubectl rollout status deploy/"${PROM_DEPLOYMENT}" -n "${NS}" --timeout=120s
echo "Prometheus scrape config updated."
