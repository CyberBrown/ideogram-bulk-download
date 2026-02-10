#!/usr/bin/env python3
"""
Ideogram Bulk Image Downloader (Browser-based)
================================================
Uses Playwright to automate a real browser, bypassing Cloudflare protection.
Intercepts the internal API calls that the Ideogram webapp makes when loading
your creations page, then downloads all images.

USAGE:
  python3 download_browser.py --session-cookie "YOUR_SESSION_COOKIE"
  
The session_cookie is the value of the 'session_cookie' cookie from ideogram.ai
(the long JWT that starts with 'eyJ...')
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright


class IdeogramBrowserDownloader:
    def __init__(self, session_cookie: str, output_dir: str = "./ideogram_images"):
        self.session_cookie = session_cookie
        self.output_dir = output_dir
        self.api_responses = []
        self.image_urls = []
        self.all_image_data = []
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    async def intercept_response(self, response):
        """Intercept API responses to capture image metadata."""
        url = response.url
        if '/api/' in url and response.status == 200:
            try:
                content_type = response.headers.get('content-type', '')
                if 'json' in content_type:
                    body = await response.json()
                    body_str = json.dumps(body)
                    # Check if this response contains image data
                    if any(k in body_str for k in ['response_id', 'thumbnail_url', 'prompt', 'image_url']):
                        self.api_responses.append({
                            'url': url,
                            'data': body
                        })
                        print(f"  📡 Captured API response: {url[:80]}")
            except Exception:
                pass
    
    def extract_images_from_responses(self):
        """Extract all unique image entries from captured API responses."""
        seen_ids = set()
        
        for resp in self.api_responses:
            data = resp['data']
            images = self._find_images_recursive(data)
            for img in images:
                img_id = img.get('response_id') or img.get('id') or img.get('request_id', '')
                if img_id and img_id not in seen_ids:
                    seen_ids.add(img_id)
                    self.all_image_data.append(img)
        
        return self.all_image_data
    
    def _find_images_recursive(self, data, depth=0):
        """Recursively search through nested data for image entries."""
        if depth > 10:
            return []
        
        results = []
        
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    # Check if this dict looks like an image entry
                    has_image_keys = any(k in item for k in ['response_id', 'url', 'image_url', 'thumbnail_url', 'prompt'])
                    if has_image_keys:
                        results.append(item)
                    else:
                        results.extend(self._find_images_recursive(item, depth + 1))
                elif isinstance(item, list):
                    results.extend(self._find_images_recursive(item, depth + 1))
        
        elif isinstance(data, dict):
            # Check if this dict itself is an image entry
            has_image_keys = any(k in data for k in ['response_id', 'url', 'image_url', 'thumbnail_url'])
            if has_image_keys and 'prompt' in data:
                results.append(data)
            
            # Also search nested values
            for key, value in data.items():
                if isinstance(value, (list, dict)):
                    results.extend(self._find_images_recursive(value, depth + 1))
        
        return results

    async def run(self):
        """Main execution: launch browser, navigate, capture, download."""
        print("=" * 60)
        print("Ideogram Bulk Image Downloader (Browser Mode)")
        print("=" * 60)
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            # Set the session cookie
            await context.add_cookies([{
                'name': 'session_cookie',
                'value': self.session_cookie,
                'domain': 'ideogram.ai',
                'path': '/',
                'httpOnly': True,
                'secure': True,
                'sameSite': 'Lax',
            }])
            
            page = await context.new_page()
            
            # Listen for API responses
            page.on('response', self.intercept_response)
            
            # Step 1: Navigate to profile page to pass Cloudflare and discover user ID
            print("\n📌 Step 1: Loading ideogram.ai...")
            try:
                await page.goto('https://ideogram.ai', wait_until='networkidle', timeout=30000)
            except Exception as e:
                print(f"  Initial load: {e}")
            
            await asyncio.sleep(3)
            
            # Check if we need to handle Cloudflare challenge
            content = await page.content()
            if 'Just a moment' in content or 'challenge' in content.lower():
                print("  ⏳ Waiting for Cloudflare challenge to resolve...")
                await asyncio.sleep(10)
                content = await page.content()
                if 'Just a moment' in content:
                    print("  ⏳ Still waiting... (15 more seconds)")
                    await asyncio.sleep(15)
            
            # Step 2: Navigate to creations/profile page
            print("\n📌 Step 2: Navigating to profile/creations page...")
            
            # Try clicking the profile link or navigating directly
            try:
                await page.goto('https://ideogram.ai/my-images', wait_until='networkidle', timeout=30000)
            except:
                pass
            await asyncio.sleep(3)
            
            # If that didn't work, try other URLs
            current_url = page.url
            print(f"  Current URL: {current_url}")
            
            if not self.api_responses:
                print("  Trying /assets...")
                try:
                    await page.goto('https://ideogram.ai/assets', wait_until='networkidle', timeout=20000)
                except:
                    pass
                await asyncio.sleep(3)
            
            if not self.api_responses:
                print("  Trying direct profile URL...")
                try:
                    await page.goto('https://ideogram.ai/u/NBWy2tr5tOZBEItRhLrbrVZvUE22', wait_until='networkidle', timeout=20000)
                except:
                    pass
                await asyncio.sleep(3)
            
            # Step 3: Scroll to load all images (infinite scroll)
            if self.api_responses:
                print(f"\n📌 Step 3: Scrolling to load all images...")
                previous_count = 0
                no_new_count = 0
                
                while no_new_count < 5:
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await asyncio.sleep(2)
                    
                    current_count = len(self.api_responses)
                    if current_count == previous_count:
                        no_new_count += 1
                        print(f"  Scroll {no_new_count}/5 with no new data ({current_count} API responses total)")
                    else:
                        no_new_count = 0
                        print(f"  New data loaded! ({current_count} API responses)")
                    previous_count = current_count
            else:
                print("\n⚠️  No API responses captured yet. Let me try to find the page structure...")
                # Dump what we can see
                content = await page.content()
                title = await page.title()
                print(f"  Page title: {title}")
                print(f"  Page URL: {page.url}")
                print(f"  Content length: {len(content)}")
                
                # Look for any navigation links
                links = await page.query_selector_all('a[href*="/u/"], a[href*="profile"], a[href*="creat"], a[href*="my-"]')
                for link in links[:10]:
                    href = await link.get_attribute('href')
                    text = await link.inner_text()
                    print(f"  Link: {text[:30]} → {href}")
                
                # Take a screenshot for debugging
                screenshot_path = os.path.join(self.output_dir, 'debug_screenshot.png')
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"\n  Screenshot saved to: {screenshot_path}")
                
                # Also dump all network requests we saw
                print(f"\n  Total API responses captured: {len(self.api_responses)}")
            
            # Step 4: Process captured data
            print(f"\n📌 Step 4: Processing captured data...")
            print(f"  Total API responses: {len(self.api_responses)}")
            
            # Save raw API responses for debugging
            raw_path = os.path.join(self.output_dir, 'raw_api_responses.json')
            with open(raw_path, 'w') as f:
                json.dump([{'url': r['url'], 'data_keys': list(r['data'].keys()) if isinstance(r['data'], dict) else type(r['data']).__name__} for r in self.api_responses], f, indent=2, default=str)
            
            images = self.extract_images_from_responses()
            print(f"  Unique images found: {len(images)}")
            
            if images:
                # Save metadata
                meta_path = os.path.join(self.output_dir, 'metadata.json')
                with open(meta_path, 'w') as f:
                    json.dump(images, f, indent=2, default=str)
                print(f"  Metadata saved to: {meta_path}")
                
                # Step 5: Download images
                print(f"\n📌 Step 5: Downloading {len(images)} images...")
                success = 0
                failed = 0
                
                for i, img in enumerate(images):
                    result = await self.download_single(page, img, i)
                    if result:
                        success += 1
                    else:
                        failed += 1
                    
                    if (i + 1) % 10 == 0:
                        print(f"  Progress: {i+1}/{len(images)}")
                        await asyncio.sleep(1)
                
                print(f"\n{'=' * 60}")
                print(f"✅ Downloaded {success}/{len(images)} images")
                if failed:
                    print(f"❌ Failed: {failed}")
            else:
                print("\n❌ No images found in API responses.")
                print("  The raw API data has been saved for debugging.")
                # Dump all responses fully for analysis
                full_path = os.path.join(self.output_dir, 'full_api_responses.json')
                with open(full_path, 'w') as f:
                    json.dump(self.api_responses, f, indent=2, default=str)
                print(f"  Full API responses: {full_path}")
            
            print(f"Output directory: {self.output_dir}")
            print("=" * 60)
            
            await browser.close()
    
    async def download_single(self, page, img_data, index):
        """Download a single image using the browser context."""
        try:
            # Try to construct download URL
            response_id = img_data.get('response_id') or img_data.get('id')
            url = None
            
            if response_id:
                url = f"https://ideogram.ai/api/images/direct/{response_id}"
            
            if not url:
                url = img_data.get('url') or img_data.get('image_url') or img_data.get('thumbnail_url')
            
            if not url:
                print(f"  ⚠️ No URL for image {index}")
                return False
            
            # Use the browser to download (bypasses Cloudflare)
            response = await page.request.get(url)
            
            if response.status != 200:
                # Try thumbnail as fallback
                thumb = img_data.get('thumbnail_url')
                if thumb and thumb != url:
                    response = await page.request.get(thumb)
                
                if response.status != 200:
                    print(f"  ❌ HTTP {response.status} for image {index}")
                    return False
            
            body = await response.body()
            
            # Determine extension
            content_type = response.headers.get('content-type', 'image/png')
            ext = 'png'
            if 'jpeg' in content_type or 'jpg' in content_type:
                ext = 'jpg'
            elif 'webp' in content_type:
                ext = 'webp'
            
            # Create filename from prompt
            prompt = img_data.get('prompt', 'unknown')
            safe_prompt = re.sub(r'[^\w\s-]', '', prompt[:60]).strip().replace(' ', '_')
            filename = f"{index:04d}_{safe_prompt}.{ext}"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'wb') as f:
                f.write(body)
            
            size_kb = len(body) / 1024
            print(f"  ✅ {filename} ({size_kb:.0f} KB)")
            return True
            
        except Exception as e:
            print(f"  ❌ Error downloading image {index}: {e}")
            return False


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Download all Ideogram images using browser automation")
    parser.add_argument("--session-cookie", "-s", 
                       help="The session_cookie value from ideogram.ai",
                       default=os.environ.get("IDEO_SESSION_COOKIE", ""))
    parser.add_argument("--output", "-o", default="./ideogram_images",
                       help="Output directory")
    
    args = parser.parse_args()
    
    # Try to load from .env
    if not args.session_cookie:
        env_file = Path(__file__).parent / ".env"
        if env_file.exists():
            content = env_file.read_text()
            # Extract session cookie from the full cookie string
            import re
            match = re.search(r'session_cookie=([^;]+)', content)
            if match:
                args.session_cookie = match.group(1)
    
    if not args.session_cookie:
        print("❌ Need session cookie. Get it from Chrome DevTools:")
        print("   1. Go to ideogram.ai in Chrome")
        print("   2. F12 → Application → Cookies → ideogram.ai")
        print("   3. Copy the value of 'session_cookie'")
        print("   4. Run: python3 download_browser.py -s 'eyJ...'")
        sys.exit(1)
    
    downloader = IdeogramBrowserDownloader(args.session_cookie, args.output)
    await downloader.run()


if __name__ == "__main__":
    asyncio.run(main())
