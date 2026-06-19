# Sample datasets

Drop bundled sample databases here. The backend auto-registers them as
read-only data sources on startup (see `backend/main.py::_seed_samples`).

## Northwind

**Put your downloaded file here, named exactly `northwind.db`:**

```
quorum/data/samples/northwind.db
```

On the next API start it appears as the data source **"Northwind (sample)"**
(`kind=sqlite`, `is_sample=true`) and is selectable for investigations. No code
changes needed — just place the file.

Chinook is also auto-registered if you add `chinook.db` or `chinook.sqlite` here.
