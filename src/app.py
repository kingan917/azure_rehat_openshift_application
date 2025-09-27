import argparse
import json
import logging
import os
import ssl
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Optional

from pymongo import MongoClient
from pymongo.errors import PyMongoError


def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def build_mongo_client() -> MongoClient:
    """
    Build a MongoClient from environment configuration. Prefer MONGODB_URI if provided.
    Supports optional TLS and replica set.
    """
    uri = os.getenv("MONGODB_URI")

    tls_enabled = env_bool("MONGODB_TLS", False)
    tls_ca_file = os.getenv("MONGODB_TLS_CA_FILE")
    tls_cert_key_file = os.getenv("MONGODB_TLS_CERT_KEY_FILE")
    replica_set = os.getenv("MONGODB_REPLICA_SET")
    direct = os.getenv("MONGODB_DIRECT_CONNECTION")
    auth_mechanism = os.getenv("MONGODB_AUTH_MECHANISM")

    if not uri:
        host = os.getenv("MONGODB_HOST", "mongodb")
        port = int(os.getenv("MONGODB_PORT", "27017"))
        username = os.getenv("MONGODB_USERNAME")
        password = os.getenv("MONGODB_PASSWORD")
        # Default authSource: use $external for X.509, otherwise admin
        default_auth_source = "$external" if (auth_mechanism == "MONGODB-X509") else "admin"
        auth_source = os.getenv("MONGODB_AUTH_SOURCE", default_auth_source)

        auth_segment = ""
        if username and password:
            auth_segment = f"{username}:{password}@"

        query_params = []
        if auth_source:
            query_params.append(f"authSource={auth_source}")
        if auth_mechanism:
            query_params.append(f"authMechanism={auth_mechanism}")
        if replica_set:
            query_params.append(f"replicaSet={replica_set}")
        if direct is not None:
            query_params.append(f"directConnection={str(direct).lower()}")
        if tls_enabled:
            query_params.append("tls=true")

        query = ("?" + "&".join(query_params)) if query_params else ""
        uri = f"mongodb://{auth_segment}{host}:{port}/{query}"

    client_kwargs = {
        "serverSelectionTimeoutMS": int(os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "5000")),
        "connectTimeoutMS": int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "5000")),
        "socketTimeoutMS": int(os.getenv("MONGODB_SOCKET_TIMEOUT_MS", "5000")),
    }

    # TLS handling
    if tls_enabled:
        client_kwargs["tls"] = True
        if tls_ca_file:
            client_kwargs["tlsCAFile"] = tls_ca_file
        if tls_cert_key_file:
            client_kwargs["tlsCertificateKeyFile"] = tls_cert_key_file
        # Allow opting into insecure if explicitly requested (not recommended)
        if env_bool("MONGODB_TLS_ALLOW_INVALID_CERTS", False):
            client_kwargs["tlsAllowInvalidCertificates"] = True
        if env_bool("MONGODB_TLS_ALLOW_INVALID_HOSTNAMES", False):
            client_kwargs["tlsAllowInvalidHostnames"] = True

    logging.info("Initializing MongoClient")
    return MongoClient(uri, **client_kwargs)


def ping(client: MongoClient) -> dict:
    """Ping the MongoDB server and return result/latency."""
    from time import perf_counter

    start = perf_counter()
    client.admin.command("ping")
    elapsed_ms = (perf_counter() - start) * 1000
    return {"ok": 1, "latency_ms": round(elapsed_ms, 2)}


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    mongo_client: Optional[MongoClient] = None

    def _send(self, code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # pragma: no cover (keep quiet)
        logging.info("%s - - " + fmt, self.address_string(), *args)

    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            return self._send(200, {"status": "ok"})
        if self.path == "/db/ping":
            try:
                result = ping(self.mongo_client)
                return self._send(200, {"status": "ok", "ping": result})
            except PyMongoError as e:
                logging.exception("MongoDB ping failed")
                return self._send(500, {"status": "error", "error": str(e)})

        return self._send(404, {"status": "not_found"})


def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="MongoDB connectivity app")
    parser.add_argument("--server", action="store_true", help="Run HTTP server mode")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")), help="HTTP server port")
    args = parser.parse_args()

    try:
        client = build_mongo_client()
    except Exception as e:  # Catch early config errors
        logging.exception("Failed creating MongoClient")
        print(f"Failed creating MongoClient: {e}", file=sys.stderr)
        sys.exit(2)

    if not args.server:
        # One-off connectivity check
        try:
            result = ping(client)
            print(json.dumps({"status": "ok", "ping": result}))
            sys.exit(0)
        except PyMongoError as e:
            logging.exception("MongoDB ping failed")
            print(json.dumps({"status": "error", "error": str(e)}))
            sys.exit(1)

    # Server mode
    Handler.mongo_client = client
    addr = ("0.0.0.0", args.port)
    httpd = ThreadingHTTPServer(addr, Handler)
    logging.info("HTTP server listening on %s:%d", *addr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
