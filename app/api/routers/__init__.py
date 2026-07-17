from app.api.routers import crawl, documents, health, jobs, research

ALL_ROUTERS = [health.router, research.router, crawl.router, documents.router, jobs.router]
