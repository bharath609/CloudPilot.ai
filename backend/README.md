# CloudPilot AI — Backend

FastAPI service for CSV ingestion, validation and exact-decimal persistence.

The project overview, setup commands and milestone status live in the
[repository README](../README.md). API documentation is served at `/docs` when
the server is running.

```bash
# from this directory, with the repository virtualenv active
alembic upgrade head
uvicorn app.main:app --reload
pytest
```
