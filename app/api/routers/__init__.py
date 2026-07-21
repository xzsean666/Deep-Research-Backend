from app.api.routers import admin, crawl, documents, health, jobs, research

ALL_ROUTERS = [
    health.router,
    research.router,
    crawl.router,
    documents.router,
    jobs.router,
    admin.router,
]
