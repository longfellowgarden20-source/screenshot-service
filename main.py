from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from playwright.async_api import async_playwright
import httpx
import os
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
STORAGE_BUCKET = "preview-screenshots"


class ScreenshotRequest(BaseModel):
    preview_id: str
    preview_url: str


async def upload_to_supabase(preview_id: str, image_bytes: bytes) -> str:
    path = f"{preview_id}.png"
    # Use PUT (upsert) so re-captures overwrite the existing file instead of 409ing
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{path}"
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            upload_url,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "image/png",
                "x-upsert": "true",
            },
            content=image_bytes,
            timeout=30,
        )
        if not resp.is_success:
            raise HTTPException(status_code=500, detail=f"Upload failed: {resp.text}")
    return f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{path}"


async def save_screenshot_url(preview_id: str, url: str):
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{SUPABASE_URL}/rest/v1/previews?id=eq.{preview_id}",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={"screenshot_url": url},
            timeout=10,
        )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/screenshot")
async def take_screenshot(req: ScreenshotRequest):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.goto(req.preview_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        image_bytes = await page.screenshot(full_page=False)
        await browser.close()

    public_url = await upload_to_supabase(req.preview_id, image_bytes)
    await save_screenshot_url(req.preview_id, public_url)

    return {"screenshot_url": public_url}
