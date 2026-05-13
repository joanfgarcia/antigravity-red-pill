import sqlite3
from pathlib import Path

import platformdirs

db_path = Path(platformdirs.user_data_dir("neon-link")) / "events.db"
conn = sqlite3.connect(db_path)
for row in conn.execute("SELECT * FROM inbox"):
	print(dict(zip([c[0] for c in conn.execute("SELECT * FROM inbox").description], row)))
