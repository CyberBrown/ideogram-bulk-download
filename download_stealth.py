#!/usr/bin/env python3
"""
Ideogram Bulk Image Downloader - Undetected Chrome Edition
===========================================================
Uses undetected-chromedriver to bypass Cloudflare bot detection.
Opens your real Chrome browser in a way that doesn't trigger anti-bot.

SETUP:
  pip install undetected-chromedriver selenium

USAGE:
  python3 download_stealth.py
"""

import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except ImportError:
    print("Install dependencies first:")
    print("  pip install undetected-chromedriver selenium")
    sys.exit(1)


def main():
    output_dir = "./ideogram_images"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Ideogram Bulk Image Downloader (Stealth Chrome)")
    print("=" * 60)

    # Launch undetected Chrome
    print("\n🌐 Launching Chrome (undetected mode)...")
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    # Don't use headless — we need to be "real"
    
    driver = uc.Chrome(options=options, version_main=None)
    
    try:
        # Navigate to ideogram
        print("📌 Opening ideogram.ai...")
        driver.get("https://ideogram.ai")
        
        print("\n⚡ Please log in if needed, then navigate to your creations/profile page.")
        print("   Once you can see your images, press Enter here...")
        input()
        
        # Now we need to find the creations page URL
        current = driver.current_url
        print(f"   Current URL: {current}")
        
        # Try navigating to my-images if not already there
        if '/my-images' not in current and '/u/' not in current:
            print("   Navigating to /my-images...")
            driver.get("https://ideogram.ai/my-images")
            time.sleep(3)
        
        # Use JavaScript to intercept fetch/XHR and capture API responses
        print("\n📡 Injecting API interceptor...")
        driver.execute_script("""
            window.__ideo_captured = [];
            
            // Intercept fetch
            const origFetch = window.fetch;
            window.fetch = async function(...args) {
                const response = await origFetch.apply(this, args);
                const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
                if (url.includes('/api/') && response.ok) {
                    try {
                        const clone = response.clone();
                        const data = await clone.json();
                        window.__ideo_captured.push({url: url, data: data});
                    } catch(e) {}
                }
                return response;
            };
            
            // Intercept XMLHttpRequest
            const origOpen = XMLHttpRequest.prototype.open;
            const origSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                this._url = url;
                return origOpen.apply(this, [method, url, ...rest]);
            };
            XMLHttpRequest.prototype.send = function(...args) {
                this.addEventListener('load', function() {
                    if (this._url && this._url.includes('/api/') && this.status === 200) {
                        try {
                            const data = JSON.parse(this.responseText);
                            window.__ideo_captured.push({url: this._url, data: data});
                        } catch(e) {}
                    }
                });
                return origSend.apply(this, args);
            };
            
            console.log('API interceptor installed');
        """)
        
        # Now scroll to trigger loading — need to reload with interceptor active
        print("   Reloading page with interceptor active...")
        driver.refresh()
        time.sleep(5)
        
        # Scroll to load all images
        print("\n🔄 Scrolling to load all images...")
        last_height = 0
        stale_count = 0
        scroll_num = 0
        
        while stale_count < 5:
            scroll_num += 1
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            captured_count = driver.execute_script("return window.__ideo_captured ? window.__ideo_captured.length : 0")
            
            if new_height == last_height:
                stale_count += 1
                print(f"   Scroll {scroll_num}: no new content (stale {stale_count}/5), {captured_count} API calls captured")
            else:
                stale_count = 0
                print(f"   Scroll {scroll_num}: page grew, {captured_count} API calls captured")
            
            last_height = new_height
        
        # Extract captured API data
        print("\n📦 Extracting captured data...")
        captured = driver.execute_script("return JSON.stringify(window.__ideo_captured || [])")
        api_data = json.loads(captured)
        print(f"   Total API responses captured: {len(api_data)}")
        
        # Save raw data
        with open(os.path.join(output_dir, "api_raw.json"), "w") as f:
            json.dump(api_data, f, indent=2, default=str)
        
        # Find all image entries
        all_images = []
        seen_ids = set()
        
        for resp in api_data:
            images = find_images(resp.get('data', {}))
            for img in images:
                rid = img.get('response_id') or img.get('id') or str(len(all_images))
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    all_images.append(img)
        
        print(f"   Unique images found: {len(all_images)}")
        
        if not all_images:
            print("\n⚠️  No images found via API interception.")
            print("   Falling back to scraping image URLs from the page...")
            all_images = scrape_page_images(driver)
            print(f"   Found {len(all_images)} images from page scraping")
        
        if not all_images:
            print("\n❌ No images found. Saving debug data...")
            with open(os.path.join(output_dir, "debug_page.html"), "w") as f:
                f.write(driver.page_source)
            print(f"   Debug HTML saved to {output_dir}/debug_page.html")
            return
        
        # Save metadata
        with open(os.path.join(output_dir, "metadata.json"), "w") as f:
            json.dump(all_images, f, indent=2, default=str)
        
        # Download all images
        print(f"\n📥 Downloading {len(all_images)} images...")
        success = 0
        failed = 0
        
        for i, img in enumerate(all_images):
            try:
                url = get_image_url(img)
                if not url:
                    failed += 1
                    continue
                
                # Use selenium to download via the authenticated session
                driver.execute_script(f"""
                    var xhr = new XMLHttpRequest();
                    xhr.open('GET', '{url}', false);
                    xhr.responseType = 'arraybuffer';
                    xhr.send();
                    if (xhr.status === 200) {{
                        var blob = new Blob([xhr.response]);
                        var a = document.createElement('a');
                        a.href = URL.createObjectURL(blob);
                        a.download = 'img_{i:04d}.png';
                        document.body.appendChild(a);
                        window.__last_download_data = btoa(String.fromCharCode.apply(null, new Uint8Array(xhr.response)));
                        window.__last_download_status = xhr.status;
                    }} else {{
                        window.__last_download_status = xhr.status;
                        window.__last_download_data = null;
                    }}
                """)
                
                status = driver.execute_script("return window.__last_download_status")
                b64data = driver.execute_script("return window.__last_download_data")
                
                if status == 200 and b64data:
                    import base64
                    img_bytes = base64.b64decode(b64data)
                    
                    prompt = img.get('prompt', 'untitled') if isinstance(img, dict) else 'untitled'
                    safe = re.sub(r'[^\w\s-]', '', prompt[:60]).strip().replace(' ', '_')
                    fname = f"{i:04d}_{safe}.png"
                    
                    with open(os.path.join(output_dir, fname), 'wb') as f:
                        f.write(img_bytes)
                    
                    success += 1
                    if (i + 1) % 10 == 0:
                        print(f"   Progress: {i+1}/{len(all_images)} ({success} OK)")
                else:
                    failed += 1
                    
            except Exception as e:
                # For large images, the base64 approach may fail
                # Fall back to direct navigation download
                try:
                    url = get_image_url(img)
                    if url:
                        success += download_via_requests(driver, url, img, i, output_dir)
                    else:
                        failed += 1
                except:
                    failed += 1
                
            time.sleep(0.3)
        
        print(f"\n{'='*60}")
        print(f"✅ Done! {success} downloaded, {failed} failed")
        print(f"📁 Output: {os.path.abspath(output_dir)}")
        print("=" * 60)
        
    finally:
        print("\nPress Enter to close the browser...")
        input()
        driver.quit()


def find_images(data, depth=0):
    """Recursively find image entries."""
    if depth > 8:
        return []
    results = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and any(k in item for k in ['response_id', 'thumbnail_url', 'url']):
                if 'prompt' in item or 'response_id' in item:
                    results.append(item)
            results.extend(find_images(item, depth + 1) if isinstance(item, (list, dict)) else [])
    elif isinstance(data, dict):
        if any(k in data for k in ['response_id']) and ('prompt' in data or 'url' in data):
            results.append(data)
        for v in data.values():
            if isinstance(v, (list, dict)):
                results.extend(find_images(v, depth + 1))
    return results


def get_image_url(img):
    """Get download URL from image data."""
    if isinstance(img, dict):
        rid = img.get('response_id') or img.get('id')
        if rid:
            return f"https://ideogram.ai/api/images/direct/{rid}"
        return img.get('url') or img.get('image_url') or img.get('thumbnail_url')
    elif isinstance(img, str):
        return img
    return None


def scrape_page_images(driver):
    """Fallback: scrape image URLs directly from the page DOM."""
    images = driver.execute_script("""
        var imgs = document.querySelectorAll('img[src*="ideogram"], img[src*="cdn"], img[loading]');
        var results = [];
        imgs.forEach(function(img) {
            var src = img.src || img.dataset.src || '';
            if (src && !src.includes('avatar') && !src.includes('icon') && !src.includes('logo')) {
                var alt = img.alt || '';
                results.push({url: src, prompt: alt});
            }
        });
        return results;
    """)
    return images or []


def download_via_requests(driver, url, img, index, output_dir):
    """Fallback download using cookies from selenium session."""
    import urllib.request
    
    cookies = driver.get_cookies()
    cookie_str = '; '.join([f"{c['name']}={c['value']}" for c in cookies])
    
    req = urllib.request.Request(url)
    req.add_header('Cookie', cookie_str)
    req.add_header('User-Agent', driver.execute_script('return navigator.userAgent'))
    
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read()
        
        prompt = img.get('prompt', 'untitled') if isinstance(img, dict) else 'untitled'
        safe = re.sub(r'[^\w\s-]', '', prompt[:60]).strip().replace(' ', '_')
        fname = f"{index:04d}_{safe}.png"
        
        with open(os.path.join(output_dir, fname), 'wb') as f:
            f.write(data)
        return 1
    except:
        return 0


if __name__ == "__main__":
    main()
