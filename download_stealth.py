#!/usr/bin/env python3
"""
Ideogram Bulk Image Downloader - Undetected Chrome Edition v2
==============================================================
Uses undetected-chromedriver to bypass Cloudflare bot detection.
Injects API interceptor via CDP before page load.

SETUP:
  pip install undetected-chromedriver selenium setuptools

USAGE:
  python3 download_stealth.py
"""

import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
except ImportError:
    print("Install dependencies first:")
    print("  pip install undetected-chromedriver selenium setuptools")
    sys.exit(1)


def detect_chrome_version():
    """Auto-detect installed Chrome/Chromium version."""
    for chrome_bin in ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser',
                       '/usr/bin/google-chrome', '/usr/bin/chromium']:
        try:
            out = subprocess.check_output([chrome_bin, '--version'], text=True, stderr=subprocess.DEVNULL).strip()
            ver = int(out.split()[-1].split('.')[0])
            print(f"   Detected {chrome_bin} → version {ver}")
            return ver
        except Exception:
            continue
    return None


# JavaScript interceptor to inject via CDP (runs before any page JS)
INTERCEPTOR_JS = """
(function() {
    window.__ideo_captured = [];
    window.__ideo_img_urls = new Set();
    
    // Intercept fetch
    const origFetch = window.fetch;
    window.fetch = async function(...args) {
        const response = await origFetch.apply(this, args);
        const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
        if (response.ok) {
            try {
                const clone = response.clone();
                const text = await clone.text();
                try {
                    const data = JSON.parse(text);
                    window.__ideo_captured.push({url: url, data: data, ts: Date.now()});
                } catch(e) {
                    // Not JSON, skip
                }
            } catch(e) {}
        }
        return response;
    };
    
    // Intercept XMLHttpRequest  
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
        this.__url = url;
        return origOpen.apply(this, [method, url, ...rest]);
    };
    XMLHttpRequest.prototype.send = function(...args) {
        this.addEventListener('load', function() {
            if (this.__url && this.status >= 200 && this.status < 300) {
                try {
                    const data = JSON.parse(this.responseText);
                    window.__ideo_captured.push({url: this.__url, data: data, ts: Date.now()});
                } catch(e) {}
            }
        });
        return origSend.apply(this, args);
    };
    
    console.log('[ideogram-dl] API interceptor installed');
})();
"""


def main():
    output_dir = "./ideogram_images"
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Ideogram Bulk Image Downloader v2 (Stealth Chrome)")
    print("=" * 60)

    # Launch undetected Chrome
    print("\n🌐 Launching Chrome (undetected mode)...")
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    
    chrome_ver = detect_chrome_version()
    if chrome_ver:
        print(f"   Using Chrome version: {chrome_ver}")
    
    driver = uc.Chrome(options=options, version_main=chrome_ver)
    
    try:
        # Inject interceptor via CDP — runs on every new document before page JS
        print("📡 Installing API interceptor (CDP)...")
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": INTERCEPTOR_JS})
        
        # Navigate to ideogram
        print("📌 Opening ideogram.ai...")
        driver.get("https://ideogram.ai")
        
        print("\n⚡ Please log in if needed.")
        print("   Once you're logged in and can see ideogram.ai, press Enter here...")
        input()
        
        # Navigate to my-images (interceptor will capture the API calls)
        print("   Navigating to your creations page...")
        driver.get("https://ideogram.ai/t/my-images")
        time.sleep(5)
        
        # Check if interceptor is alive
        alive = driver.execute_script("return typeof window.__ideo_captured !== 'undefined'")
        captured_so_far = driver.execute_script("return window.__ideo_captured ? window.__ideo_captured.length : -1")
        print(f"   Interceptor active: {alive}, captured so far: {captured_so_far}")
        
        if not alive:
            print("   ⚠️ Interceptor lost after navigation. Re-injecting...")
            driver.execute_script(INTERCEPTOR_JS)
            driver.refresh()
            time.sleep(5)
        
        # Scroll to load ALL images
        print("\n🔄 Scrolling to load all images (this may take a while)...")
        last_height = 0
        stale_count = 0
        scroll_num = 0
        
        while stale_count < 8:  # More patience
            scroll_num += 1
            
            # Scroll to bottom
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            
            # Also try scrolling the main content container
            driver.execute_script("""
                var containers = document.querySelectorAll('[class*="scroll"], [class*="grid"], main, [role="main"]');
                containers.forEach(function(c) {
                    c.scrollTop = c.scrollHeight;
                });
            """)
            time.sleep(1)
            
            new_height = driver.execute_script("return document.body.scrollHeight")
            captured_count = driver.execute_script("return window.__ideo_captured ? window.__ideo_captured.length : 0")
            img_count = driver.execute_script("return document.querySelectorAll('img').length")
            
            if new_height == last_height:
                stale_count += 1
                print(f"   Scroll {scroll_num}: stale ({stale_count}/8) | {captured_count} API calls | {img_count} imgs in DOM")
            else:
                stale_count = 0
                print(f"   Scroll {scroll_num}: loading... | {captured_count} API calls | {img_count} imgs in DOM")
            
            last_height = new_height
        
        # Extract captured API data
        print("\n📦 Extracting captured API data...")
        captured = driver.execute_script("return JSON.stringify(window.__ideo_captured || [])")
        api_data = json.loads(captured)
        print(f"   Total API responses captured: {len(api_data)}")
        
        if api_data:
            # Log what endpoints were hit
            endpoints = set()
            for r in api_data:
                endpoints.add(r.get('url', 'unknown'))
            print(f"   Endpoints seen: {len(endpoints)}")
            for ep in sorted(endpoints):
                print(f"     - {ep}")
        
        # Save raw API data
        with open(os.path.join(output_dir, "api_raw.json"), "w") as f:
            json.dump(api_data, f, indent=2, default=str)
        
        # Find images from API data
        all_images = []
        seen_ids = set()
        
        for resp in api_data:
            images = find_images_recursive(resp.get('data', {}))
            for img in images:
                rid = img.get('response_id') or img.get('id')
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    all_images.append(img)
        
        print(f"   Images from API: {len(all_images)}")
        
        # Also scrape DOM for any images the API might have missed
        print("\n🔍 Scraping page DOM for image URLs...")
        dom_images = scrape_all_images(driver)
        print(f"   Images from DOM: {len(dom_images)}")
        
        # Merge: prefer API data, supplement with DOM
        dom_only = []
        for di in dom_images:
            url = di.get('url', '')
            # Check if we already have this from API
            already_have = False
            for ai in all_images:
                if ai.get('response_id') and ai['response_id'] in url:
                    already_have = True
                    break
            if not already_have:
                dom_only.append(di)
        
        if dom_only:
            print(f"   Additional images from DOM not in API: {len(dom_only)}")
            all_images.extend(dom_only)
        
        total = len(all_images)
        print(f"\n   Total unique images to download: {total}")
        
        if total == 0:
            print("\n❌ No images found. Saving debug data...")
            with open(os.path.join(output_dir, "debug_page.html"), "w") as f:
                f.write(driver.page_source)
            return
        
        # Save metadata
        with open(os.path.join(output_dir, "metadata.json"), "w") as f:
            json.dump(all_images, f, indent=2, default=str)
        
        # Download all images
        print(f"\n📥 Downloading {total} images...")
        success = 0
        failed = 0
        
        for i, img in enumerate(all_images):
            url = get_best_url(img)
            if not url:
                failed += 1
                continue
            
            prompt = ''
            if isinstance(img, dict):
                prompt = img.get('prompt', '') or img.get('alt', '') or ''
            safe = re.sub(r'[^\w\s-]', '', prompt[:60]).strip().replace(' ', '_') or 'image'
            fname = f"{i:04d}_{safe}.png"
            fpath = os.path.join(output_dir, fname)
            
            ok = download_image(driver, url, fpath)
            if ok:
                success += 1
            else:
                # Try thumbnail URL as fallback
                thumb = img.get('thumbnail_url') or img.get('url', '') if isinstance(img, dict) else ''
                if thumb and thumb != url:
                    ok = download_image(driver, thumb, fpath)
                    if ok:
                        success += 1
                    else:
                        failed += 1
                else:
                    failed += 1
            
            if (i + 1) % 10 == 0 or (i + 1) == total:
                print(f"   Progress: {i+1}/{total} ({success} OK, {failed} failed)")
            
            time.sleep(0.3)
        
        print(f"\n{'='*60}")
        print(f"✅ Done! {success} downloaded, {failed} failed")
        print(f"📁 Output: {os.path.abspath(output_dir)}")
        print("=" * 60)
        
    finally:
        print("\nPress Enter to close the browser...")
        input()
        driver.quit()


def download_image(driver, url, filepath):
    """Download image using the browser's authenticated session."""
    try:
        driver.execute_script("""
            var xhr = new XMLHttpRequest();
            xhr.open('GET', arguments[0], false);
            xhr.responseType = 'arraybuffer';
            xhr.send();
            window.__dl_status = xhr.status;
            window.__dl_data = null;
            if (xhr.status === 200) {
                var bytes = new Uint8Array(xhr.response);
                var binary = '';
                var chunkSize = 8192;
                for (var j = 0; j < bytes.length; j += chunkSize) {
                    var chunk = bytes.subarray(j, Math.min(j + chunkSize, bytes.length));
                    binary += String.fromCharCode.apply(null, chunk);
                }
                window.__dl_data = btoa(binary);
            }
        """, url)
        
        status = driver.execute_script("return window.__dl_status")
        b64data = driver.execute_script("return window.__dl_data")
        
        if status == 200 and b64data:
            img_bytes = base64.b64decode(b64data)
            if len(img_bytes) > 1000:  # Skip tiny/broken files
                with open(filepath, 'wb') as f:
                    f.write(img_bytes)
                return True
        return False
    except Exception:
        return False


def find_images_recursive(data, depth=0):
    """Recursively find image entries in API response data."""
    if depth > 10:
        return []
    results = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                if 'response_id' in item:
                    results.append(item)
                else:
                    results.extend(find_images_recursive(item, depth + 1))
            elif isinstance(item, list):
                results.extend(find_images_recursive(item, depth + 1))
    elif isinstance(data, dict):
        if 'response_id' in data:
            results.append(data)
        for v in data.values():
            if isinstance(v, (list, dict)):
                results.extend(find_images_recursive(v, depth + 1))
    return results


def get_best_url(img):
    """Get the best (highest res) URL for an image."""
    if isinstance(img, dict):
        # Prefer direct API endpoint for full res
        rid = img.get('response_id') or img.get('id')
        if rid:
            return f"https://ideogram.ai/api/images/direct/{rid}"
        
        # Fall back to URL fields
        for key in ['url', 'image_url', 'src', 'thumbnail_url']:
            if key in img and img[key]:
                url = img[key]
                # Try to upgrade thumbnail to full res
                if 'thumbnail' in url or '_thumb' in url or 'small' in url:
                    # Try removing size params
                    full = re.sub(r'[?&](w|h|width|height|size|quality)=[^&]*', '', url)
                    return full
                return url
    elif isinstance(img, str):
        return img
    return None


def scrape_all_images(driver):
    """Scrape all image data from the page DOM."""
    images = driver.execute_script("""
        var results = [];
        var seen = new Set();
        
        // Get all img elements
        var imgs = document.querySelectorAll('img');
        imgs.forEach(function(img) {
            var src = img.src || img.dataset.src || '';
            if (!src || src.startsWith('data:')) return;
            if (src.includes('avatar') || src.includes('icon') || src.includes('logo') || 
                src.includes('favicon') || src.includes('sprite') || src.includes('emoji')) return;
            if (seen.has(src)) return;
            seen.add(src);
            
            var alt = img.alt || '';
            var width = img.naturalWidth || img.width || 0;
            var height = img.naturalHeight || img.height || 0;
            
            results.push({
                url: src,
                alt: alt,
                prompt: alt,
                width: width,
                height: height
            });
        });
        
        // Also check background images on divs (some sites use this)
        var divs = document.querySelectorAll('div[style*="background-image"]');
        divs.forEach(function(div) {
            var style = div.style.backgroundImage || '';
            var match = style.match(/url\\(["']?([^"')]+)["']?\\)/);
            if (match && match[1]) {
                var src = match[1];
                if (!seen.has(src) && !src.includes('avatar') && !src.includes('icon')) {
                    seen.add(src);
                    results.push({url: src, prompt: '', width: 0, height: 0});
                }
            }
        });
        
        return results;
    """)
    
    # Filter to likely actual generated images (not UI elements)
    filtered = []
    for img in (images or []):
        url = img.get('url', '')
        w = img.get('width', 0)
        h = img.get('height', 0)
        # Keep images that are reasonably large or from CDN
        if w > 100 or h > 100 or 'cdn' in url or 'ideogram' in url or 'generation' in url:
            filtered.append(img)
    
    return filtered


if __name__ == "__main__":
    main()
