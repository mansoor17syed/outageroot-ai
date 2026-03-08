# Kind Real-Test Lab for OutageRoot

This lab adds more realistic metrics into your kind setup so OutageRoot can analyze richer incidents.

## What it adds

- `pushgateway` for synthetic incident metrics
- `node-exporter-lite` for host/node-like metrics
- Prometheus scrape config for these targets

## 1) Apply monitoring add-ons

```bash
cd /home/mansoora/hustle/outageroot/kind_lab
kubectl apply -f monitoring_addons.yaml
kubectl get pods -n monitoring -w
```

## 2) Configure Prometheus scrape jobs

```bash
chmod +x configure_prom_scrape.sh generate_test_metrics.sh
./configure_prom_scrape.sh
```

## 3) Port-forward Prometheus + Pushgateway

Use two terminals:

```bash
kubectl port-forward -n monitoring svc/prom 9090:9090
```

```bash
kubectl port-forward -n monitoring svc/pushgateway 9091:9091
```

## 4) Generate synthetic metrics

```bash
./generate_test_metrics.sh
```

Now verify in Prometheus:

- `outageroot_error_rate`
- `outageroot_latency_ms`
- `outageroot_cpu_burst`
- `up{job="pushgateway"}`
- `up{job="node-exporter-lite"}`

## 5) Use these OutageRoot queries

```text
up
up{job="pushgateway"}
up{job="node-exporter-lite"}
outageroot_error_rate
outageroot_latency_ms
rate(prometheus_http_requests_total[5m])
```

## Optional: induce extra signal in cluster

```bash
kubectl create ns demo --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n demo -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: crashy-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: crashy-app
  template:
    metadata:
      labels:
        app: crashy-app
    spec:
      containers:
      - name: app
        image: busybox
        command: ["sh","-c","echo crash && sleep 2 && exit 1"]
EOF
kubectl get pods -n demo -w
```
