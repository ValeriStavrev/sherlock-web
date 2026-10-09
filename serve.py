import os
from waitress import serve
from app import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    threads = int(os.getenv("WAITRESS_THREADS", "8"))
    serve(app, host="0.0.0.0", port=port, threads=threads)
