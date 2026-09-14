"""Copy an already built frontend into the FastAPI package. Run after npm run build."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
source = root / "frontend" / "dist" / "client"
target = root / "app" / "static"
if not (source / "index.html").is_file():
    raise SystemExit("First run npm ci and npm run build inside frontend/.")
# Only this generated directory is replaced, not source or user configuration.
if target.exists():
    shutil.rmtree(target)
shutil.copytree(source, target)
print("Dashboard copied into app/static. Restart FastAPI after the first build.")
