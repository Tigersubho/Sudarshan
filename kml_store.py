"""
Where saved KML drawings live.

Two interchangeable backends with the same small interface:

    FileStore      one .kml file per drawing in a folder (default; local use)
    PostgresStore  one row per drawing in a Postgres table (used when the
                   DATABASE_URL environment variable is set, e.g. a free
                   Neon database, because free hosts like Render's free
                   plan wipe the local disk on every redeploy / sleep)

Either way the stored content is a plain KML document, so a drawing can
always be exported and opened in Google Earth / QGIS.
"""

import os
import time

KML_EXTENSION = ".kml"


class FileStore:
    kind = "files"

    def __init__(self, directory):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    def _path(self, file_id):
        return os.path.join(self.directory, f"{file_id}{KML_EXTENSION}")

    def list_all(self):
        """[(id, kml_text, modified_epoch), ...]"""

        items = []

        for entry in os.listdir(self.directory):
            if not entry.lower().endswith(KML_EXTENSION):
                continue

            path = os.path.join(self.directory, entry)

            try:
                with open(path, "r", encoding="utf-8") as handle:
                    items.append((
                        entry[: -len(KML_EXTENSION)],
                        handle.read(),
                        os.path.getmtime(path)
                    ))
            except OSError:
                continue

        return items

    def get(self, file_id):
        try:
            with open(self._path(file_id), "r", encoding="utf-8") as handle:
                return handle.read()
        except FileNotFoundError:
            return None

    def exists(self, file_id):
        return os.path.isfile(self._path(file_id))

    def put(self, file_id, content):
        with open(self._path(file_id), "w", encoding="utf-8") as handle:
            handle.write(content)

    def delete(self, file_id):
        try:
            os.remove(self._path(file_id))
            return True
        except FileNotFoundError:
            return False

    def rename(self, old_id, new_id, content):
        self.put(old_id, content)

        if new_id != old_id:
            os.replace(self._path(old_id), self._path(new_id))


class PostgresStore:
    kind = "postgres"

    def __init__(self, database_url):
        import psycopg  # imported here so local use doesn't need it

        self._psycopg = psycopg
        self.url = database_url
        self._ready = False

    def _connect(self):
        conn = self._psycopg.connect(self.url, connect_timeout=20)

        if not self._ready:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS kml_drawings ("
                " id TEXT PRIMARY KEY,"
                " content TEXT NOT NULL,"
                " modified DOUBLE PRECISION NOT NULL)"
            )
            conn.commit()
            self._ready = True

        return conn

    def list_all(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, content, modified FROM kml_drawings"
            ).fetchall()

        return [(r[0], r[1], r[2]) for r in rows]

    def get(self, file_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content FROM kml_drawings WHERE id = %s", (file_id,)
            ).fetchone()

        return row[0] if row else None

    def exists(self, file_id):
        return self.get(file_id) is not None

    def put(self, file_id, content):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO kml_drawings (id, content, modified)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (id) DO UPDATE"
                " SET content = EXCLUDED.content, modified = EXCLUDED.modified",
                (file_id, content, time.time())
            )

    def delete(self, file_id):
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM kml_drawings WHERE id = %s", (file_id,)
            )
            return cursor.rowcount > 0

    def rename(self, old_id, new_id, content):
        # One transaction, so a failure can't leave both or neither.
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO kml_drawings (id, content, modified)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (id) DO UPDATE"
                " SET content = EXCLUDED.content, modified = EXCLUDED.modified",
                (new_id, content, time.time())
            )

            if new_id != old_id:
                conn.execute("DELETE FROM kml_drawings WHERE id = %s", (old_id,))


def make_store(data_dir):
    """Postgres if DATABASE_URL is set, otherwise files under data_dir/kml."""

    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        return PostgresStore(database_url)

    return FileStore(os.path.join(data_dir, "kml"))
