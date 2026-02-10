#!/usr/bin/env python3
"""
Ideogram Bulk Image Downloader - Local Browser Edition
=======================================================
Run this on YOUR machine (not a server) where you're logged into ideogram.ai.

This uses Playwright with your existing Chrome profile to bypass Cloudflare,
intercepts the API calls your browser makes, and downloads all images.

SETUP:
  pip install playwright
  playwright install chromium

USAGE:
  # Method 1: Use your existing Chrome session (recommended)
  python3 download_local.py --chrome-profile
  
  # Method 2: Headed browser — it opens a browser, you log in manually
  python3 download_local.py --headed
  
  # Method 3: Pass session cookie directly
  python3 download_local.py --session-cookie "eyJ..."
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright


class IdeogramDownloader:
    def __init__(self, output_dir="./ideogram_images"):
        self.output_dir = output_dir
        self.api_responses = []
        self.all_image_data = []
        self.user_id = None
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    async def on_response(self, response):
        """Intercept all API responses."""
        url = response.url
        if '/api/' not in url:
            return
        if response.status != 200:
            return
        try:
            ct = response.headers.get('content-type', '')
            if 'json' not in ct:
                return
            body = await response.json()
            self.api_responses.append({'url': url, 'data': body})
            
            # Try to detect user_id
            body_str = json.dumps(body)
            if 'user_id' in body_str and not self.user_id:
                if isinstance(body, dict) and 'user_id' in body:
                    self.user_id = body['user_id']
                    
            # Count image-like entries
            images = self._find_images(body)
            if images:
                print(f"  📡 {url[:70]}... → {len(images)} images")
        except:
            pass

    def _find_images(self, data, depth=0):
        """Find image entries in nested data."""
        if depth > 8:
            return []
        results = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and any(k in item for k in ['response_id', 'url', 'thumbnail_url']):
                    results.append(item)
                else:
                    results.extend(self._find_images(item, depth+1))
        elif isinstance(data, dict):
            if any(k in data for k in ['response_id']) and 'prompt' in data:
                results.append(data)
            for v in data.values():
                if isinstance(v, (list, dict)):
                    results.extend(self._find_images(v, depth+1))
        return results

    def extract_all_images(self):
        """Deduplicate all captured images."""
        seen = set()
        for resp in self.api_responses:
            for img in self._find_images(resp['data']):
                rid = img.get('response_id') or img.get('id') or id(img)
                if rid not in seen:
                    seen.add(rid)
                    self.all_image_data.append(img)
        return self.all_image_data

    async def scroll_and_capture(self, page, max_scrolls=100):
        """Scroll down to trigger loading of all images."""
        print("\n🔄 Scrolling to load all images...")
        prev_count = 0
        stale = 0
        
        for i in range(max_scrolls):
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await asyncio.sleep(1.5)
            
            cur = sum(len(self._find_images(r['data'])) for r in self.api_responses)
            if cur == prev_count:
                stale += 1
                if stale >= 5:
                    print(f"  No new images after {stale} scrolls. Done loading.")
                    break
            else:
                stale = 0
                print(f"  Scroll {i+1}: {cur} images found so far")
            prev_count = cur
        
        return self.extract_all_images()

    async def download_images(self, page, images):
        """Download all images using browser context."""
        print(f"\n📥 Downloading {len(images)} images to {self.output_dir}/")
        
        success = 0
        failed = 0
        
        for i, img in enumerate(images):
            try:
                rid = img.get('response_id') or img.get('id')
                url = None
                
                if rid:
                    url = f"https://ideogram.ai/api/images/direct/{rid}"
                if not url:
                    url = img.get('url') or img.get('image_url') or img.get('thumbnail_url')
                if not url:
                    failed += 1
                    continue
                
                resp = await page.request.get(url)
                if resp.status != 200:
                    # Fallback to thumbnail
                    thumb = img.get('thumbnail_url')
                    if thumb:
                        resp = await page.request.get(thumb)
                
                if resp.status != 200:
                    print(f"  ❌ {i:04d}: HTTP {resp.status}")
                    failed += 1
                    continue
                
                body = await resp.body()
                ct = resp.headers.get('content-type', 'image/png')
                ext = 'jpg' if 'jpeg' in ct or 'jpg' in ct else 'webp' if 'webp' in ct else 'png'
                
                prompt = img.get('prompt', 'untitled')
                safe = re.sub(r'[^\w\s-]', '', prompt[:60]).strip().replace(' ', '_')
                fname = f"{i:04d}_{safe}.{ext}"
                
                with open(os.path.join(self.output_dir, fname), 'wb') as f:
                    f.write(body)
                
                success += 1
                if (i+1) % 20 == 0:
                    print(f"  Progress: {i+1}/{len(images)} ({success} OK, {failed} failed)")
                    await asyncio.sleep(0.5)
                    
            except Exception as e:
                print(f"  ❌ {i:04d}: {e}")
                failed += 1
        
        return success, failed

    async def run_headed(self, session_cookie=None):
        """Run with a visible browser window."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(viewport={'width': 1920, 'height': 1080})
            
            if session_cookie:
                await context.add_cookies([{
                    'name': 'session_cookie',
                    'value': session_cookie,
                    'domain': 'ideogram.ai',
                    'path': '/',
                    'httpOnly': True,
                    'secure': True,
                    'sameSite': 'Lax',
                }])
            
            page = await context.new_page()
            page.on('response', self.on_response)
            
            print("🌐 Opening ideogram.ai...")
            await page.goto('https://ideogram.ai')
            await asyncio.sleep(5)
            
            if not session_cookie:
                print("\n⚡ Please log in to ideogram.ai in the browser window!")
                print("   Press Enter here once you're logged in and on your profile page...")
                await asyncio.to_thread(input)
            
            # Navigate to profile/creations
            print("📌 Navigating to your creations...")
            
            # Try clicking profile or my-images
            try:
                await page.goto('https://ideogram.ai/my-images', wait_until='networkidle', timeout=15000)
            except:
                pass
            await asyncio.sleep(3)
            
            # If no API responses yet, the URL might differ
            if not self.api_responses:
                try:
                    await page.goto('https://ideogram.ai/assets', wait_until='networkidle', timeout=15000)
                except:
                    pass
                await asyncio.sleep(3)
            
            # Scroll to load everything
            images = await self.scroll_and_capture(page)
            
            if images:
                # Save metadata
                meta = os.path.join(self.output_dir, 'metadata.json')
                with open(meta, 'w') as f:
                    json.dump(images, f, indent=2, default=str)
                print(f"\n📄 Saved metadata: {meta}")
                
                # Download
                ok, fail = await self.download_images(page, images)
                print(f"\n{'='*60}")
                print(f"✅ Done! {ok} downloaded, {fail} failed")
                print(f"📁 Output: {os.path.abspath(self.output_dir)}")
            else:
                print("\n❌ No images found. Try navigating to your creations page manually.")
                print("   The browser window is still open — navigate there, then press Enter.")
                await asyncio.to_thread(input)
                images = await self.scroll_and_capture(page)
                if images:
                    ok, fail = await self.download_images(page, images)
                    print(f"✅ Done! {ok} downloaded, {fail} failed")
            
            # Save all API data for debugging
            with open(os.path.join(self.output_dir, 'api_debug.json'), 'w') as f:
                json.dump([{'url': r['url']} for r in self.api_responses], f, indent=2)
            
            await browser.close()

    async def run_chrome_profile(self):
        """Run using the user's existing Chrome profile."""
        # Find Chrome user data directory
        home = Path.home()
        chrome_paths = [
            home / '.config/google-chrome',           # Linux
            home / 'Library/Application Support/Google/Chrome',  # macOS
            home / 'AppData/Local/Google/Chrome/User Data',      # Windows
        ]
        
        user_data_dir = None
        for p in chrome_paths:
            if p.exists():
                user_data_dir = str(p)
                break
        
        if not user_data_dir:
            print("❌ Chrome profile not found. Use --headed mode instead.")
            sys.exit(1)
        
        print(f"📂 Using Chrome profile: {user_data_dir}")
        print("⚠️  Close all Chrome windows first!")
        
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,
                viewport={'width': 1920, 'height': 1080},
                channel='chrome',  # Use installed Chrome
            )
            
            page = context.pages[0] if context.pages else await context.new_page()
            page.on('response', self.on_response)
            
            print("🌐 Loading ideogram.ai with your Chrome session...")
            await page.goto('https://ideogram.ai/my-images', wait_until='networkidle', timeout=30000)
            await asyncio.sleep(5)
            
            images = await self.scroll_and_capture(page)
            
            if images:
                with open(os.path.join(self.output_dir, 'metadata.json'), 'w') as f:
                    json.dump(images, f, indent=2, default=str)
                ok, fail = await self.download_images(page, images)
                print(f"\n✅ Done! {ok} downloaded, {fail} failed")
                print(f"📁 Output: {os.path.abspath(self.output_dir)}")
            
            await context.close()


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--headed', action='store_true', help='Open a browser window (you log in manually)')
    parser.add_argument('--chrome-profile', action='store_true', help='Use your existing Chrome profile')
    parser.add_argument('--session-cookie', '-s', help='Session cookie value')
    parser.add_argument('--output', '-o', default='./ideogram_images', help='Output directory')
    args = parser.parse_args()
    
    dl = IdeogramDownloader(args.output)
    
    if args.chrome_profile:
        await dl.run_chrome_profile()
    elif args.headed or args.session_cookie:
        await dl.run_headed(args.session_cookie)
    else:
        print("Choose a mode:")
        print("  --chrome-profile   Use your existing Chrome login (close Chrome first)")
        print("  --headed           Opens a browser, you log in manually")
        print("  -s COOKIE          Pass session cookie directly")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
