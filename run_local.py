import os
from pathlib import Path

from app import app

if __name__ == "__main__":
    print("Sherlock Web - http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
