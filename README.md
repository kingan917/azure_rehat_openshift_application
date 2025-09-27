# Azure Red Hat OpenShift Python App (MongoDB)

This repository contains a minimal Python application that connects to a MongoDB instance running inside a Kubernetes/Red Hat OpenShift cluster. It supports both one‑off connectivity checks and a lightweight HTTP server with health and DB ping endpoints for running inside a Pod.

## Features
- Connects to MongoDB using `pymongo`
- Configurable via environment variables or a full MongoDB connection string
- Optional TLS with CA bundle support
- Simple HTTP server with `/healthz` and `/db/ping` endpoints (no extra deps)
- Dockerfile and Kubernetes/OpenShift manifests included

## Quick Start (Local)

1. Install dependencies:

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Provide a connection string via `MONGODB_URI` or components (see Env Vars below). Example with URI:

   ```bash
   export MONGODB_URI='mongodb://user:pass@mongo-svc.mongo-namespace.svc.cluster.local:27017/?authSource=admin'
   ```

3. Run a one‑off connectivity check:

   ```bash
   python src/app.py
   ```

4. Run the HTTP server (for liveness/readiness and on-demand ping):

   ```bash
   python src/app.py --server --port 8080
   # Then curl http://localhost:8080/healthz and /db/ping
   ```

## Environment Variables

You can use a full connection string via `MONGODB_URI` (recommended), or specify components:

- `MONGODB_URI` – Full connection string. Example: `mongodb://user:pass@mongo-svc.ns.svc.cluster.local:27017/?authSource=admin&tls=true`
- Component options if `MONGODB_URI` is not set:
  - `MONGODB_HOST` (default: `mongodb`)
  - `MONGODB_PORT` (default: `27017`)
  - `MONGODB_USERNAME` / `MONGODB_PASSWORD`
  - `MONGODB_AUTH_SOURCE` (default: `admin`, or `$external` if `MONGODB_AUTH_MECHANISM=MONGODB-X509`)
  - `MONGODB_AUTH_MECHANISM` (e.g., `MONGODB-X509`)
  - `MONGODB_REPLICA_SET` (optional)
  - `MONGODB_TLS` (`true`/`false`, default: `false`)
  - `MONGODB_TLS_CA_FILE` (path to CA file; required if TLS uses a custom CA)
  - `MONGODB_TLS_CERT_KEY_FILE` (path to client cert+key PEM for X.509)
  - `MONGODB_DIRECT_CONNECTION` (`true`/`false`, optional)

Server run options:
- `--server` to run the HTTP server instead of one‑off check
- `--port` to set server port (default `8080`)

## Docker

Build and run locally:

```bash
docker build -t aro-mongo-app:local .
docker run --rm -e MONGODB_URI="$MONGODB_URI" -p 8080:8080 aro-mongo-app:local
# Then curl http://localhost:8080/db/ping
```

## Kubernetes/OpenShift Deployment

1. Create a Secret containing the MongoDB connection string (recommended):

```bash
kubectl create secret generic mongodb-credentials \
  --from-literal=uri='mongodb://user:pass@mongo-svc.mongo-namespace.svc.cluster.local:27017/?authSource=admin'
```

If TLS with a custom CA is required, also create a Secret with the CA file and mount it:

```bash
kubectl create secret generic mongodb-ca \
  --from-file=tls-ca.crt=./ca.crt
```

If using X.509 client certificate authentication, create a Secret for the client PEM (certificate + key):

```bash
kubectl create secret generic mongodb-client-cert \
  --from-file=client.pem=./client.pem
```

2. Deploy the app (update image reference as needed):

```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

3. Verify liveness/readiness and DB ping:

- Inside cluster: `curl http://<pod-ip>:8080/healthz` and `/db/ping`
- Port-forward: `kubectl port-forward deploy/aro-mongo-app 8080:8080` then curl `http://localhost:8080/db/ping`

## Notes for OpenShift

- Use an ImageStream or external registry image reference in `k8s/deployment.yaml` per your workflow.
- If your cluster enforces default non‑root UIDs, the container image and file permissions are compatible with arbitrary user IDs.
- To expose publicly on OpenShift, create a Route referencing the Service, or use `kubectl port-forward` for testing.

## Troubleshooting

- Connection timeouts: ensure Service DNS resolves from the Pod and firewall rules allow access.
- Auth errors: confirm `MONGODB_AUTH_SOURCE`, username/password, and role permissions.
- TLS errors: set `MONGODB_TLS=true` and point `MONGODB_TLS_CA_FILE` to the mounted CA path.
- Replica sets: set `MONGODB_REPLICA_SET` or include `replicaSet=` in `MONGODB_URI`.

## Mapping your mongosh test to env vars

Given your working `mongosh` invocation:

```
/proc/<proc-id>/root/bin/mongosh \
  --host my-replica-set-0.my-replica-set-svc.mongodb.svc.cluster.local \
  --port 27017 \
  --tls \
  --tlsCAFile /mongodb-automation/tls/ca/ca-pem \
  --tlsCertificateKeyFile /tmp/client.pem \
  --authenticationDatabase '$external' \
  --authenticationMechanism MONGODB-X509
```

Set the following for the Python app:

```bash
export MONGODB_HOST="my-replica-set-0.my-replica-set-svc.mongodb.svc.cluster.local"
export MONGODB_PORT="27017"
export MONGODB_TLS="true"
export MONGODB_TLS_CA_FILE="/mongodb-automation/tls/ca/ca-pem"
export MONGODB_TLS_CERT_KEY_FILE="/tmp/client.pem"
export MONGODB_AUTH_MECHANISM="MONGODB-X509"
export MONGODB_AUTH_SOURCE="$external"
```

Alternatively, use a URI with equivalent options:

```bash
export MONGODB_URI="mongodb://my-replica-set-0.my-replica-set-svc.mongodb.svc.cluster.local:27017/?tls=true&authMechanism=MONGODB-X509&authSource=%24external"
export MONGODB_TLS_CA_FILE="/mongodb-automation/tls/ca/ca-pem"
export MONGODB_TLS_CERT_KEY_FILE="/tmp/client.pem"
```
