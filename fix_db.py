import sqlite3
from pathlib import Path

import platformdirs

db_path = Path(platformdirs.user_data_dir("neon-link")) / "events.db"
conn = sqlite3.connect(db_path)
conn.execute("UPDATE telegram_sessions SET cascade_id = 'd2c1b9b5-5bdc-43d3-a58a-3c236401b25a'")
conn.commit()
conn.close()
print("Fixed events.db")
