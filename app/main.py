from fastapi import FastAPI

app = FastAPI(
    title="Cartly API", description="AI-Agent Middleware for E-Grocery", version="0.1.0"
)


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
