"""tests/test_backend_phase4.py — Phase 4: schema discovery, bounded scope,
data dictionary, and encrypted external credentials (offline, SQLite)."""
import os, sys, types, sqlite3, tempfile
sys.modules.setdefault("litellm", types.ModuleType("litellm"))
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0, ROOT); os.chdir(ROOT)

from cryptography.fernet import Fernet
os.environ["CREDENTIAL_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

# tiny db
DB = tempfile.mktemp(suffix=".db")
con=sqlite3.connect(DB)
con.executescript("CREATE TABLE Genre(GenreId INT, Name TEXT); CREATE TABLE Track(TrackId INT, GenreId INT);"
                  "CREATE TABLE Customer(CustomerId INT, Country TEXT, City TEXT, Email TEXT, Phone TEXT, Fax TEXT, Zip TEXT);")
con.commit(); con.close()

from fastapi.testclient import TestClient   # noqa: E402
from backend.main import create_app          # noqa: E402
from backend.db.base import SessionLocal, Base, engine  # noqa: E402
from backend.db import models                 # noqa: E402
from backend.services.crypto import decrypt_credentials  # noqa: E402

Base.metadata.create_all(bind=engine)


def main():
    db=SessionLocal()
    ds=models.DataSource(kind="sqlite", display_name="tiny", connection_meta={"path":DB})
    db.add(ds); db.commit(); ds_id=ds.id; db.close()

    with TestClient(create_app()) as c:
        sch=c.get(f"/data-sources/{ds_id}/schema").json()
        names={t["name"] for t in sch["tables"]}
        assert {"Genre","Track","Customer"} <= names, names
        print("PASS discover schema:", sorted(names))

        sug=c.get(f"/data-sources/{ds_id}/schema/suggest").json()
        assert len(sug["tables"])<=3
        print("PASS suggest (<=3 tables):", sug["tables"])

        # too many columns -> 400 (limit 5)
        bad=c.post("/schema-scopes", json={"data_source_id":ds_id,"tables":["Customer"],
            "columns":{"Customer":["CustomerId","Country","City","Email","Phone","Fax"]}})
        assert bad.status_code==400, bad.status_code
        # valid (<=5 tables, <=5 cols) -> 200
        ok=c.post("/schema-scopes", json={"data_source_id":ds_id,"tables":["Genre","Track","Customer"],
            "columns":{"Customer":["CustomerId","Country","City","Email","Phone"]}})
        assert ok.status_code==200, ok.text
        print("PASS scope limits enforced (6 cols=400, 5 cols + 3 tables=200)")

        sk=c.post(f"/data-sources/{ds_id}/dictionary/skeleton").json()
        assert sk["count"]>0 and sk["source_kind"]=="skeleton"
        up=c.post(f"/data-sources/{ds_id}/dictionary",
                  files={"file":("d.csv", b"table,column,description\nGenre,Name,genre name","text/csv")}).json()
        assert up["source_kind"]=="uploaded" and up["count"]==1
        print(f"PASS dictionary: skeleton={sk['count']} entries, csv upload={up['count']}")

        # encrypted external connect
        ext=c.post("/data-sources/connect", json={"kind":"postgres","display_name":"prod",
            "connection_meta":{"host":"db.example","dbname":"sales"},
            "credentials":{"user":"u","password":"sekret"}}).json()
        assert ext["credentials_encrypted"] is True
        # verify encrypted-at-rest + decrypts; secret NOT in connection_meta
        db=SessionLocal(); row=db.get(models.DataSource, ext["id"])
        assert row.encrypted_credentials and b"sekret" not in row.encrypted_credentials
        assert "password" not in (row.connection_meta or {})
        assert decrypt_credentials(row.encrypted_credentials)["password"]=="sekret"
        db.close()
        print("PASS external connect: credentials encrypted at rest, decrypt round-trips")

    print("\nALL BACKEND PHASE 4 TESTS PASSED")


if __name__=="__main__":
    main()
