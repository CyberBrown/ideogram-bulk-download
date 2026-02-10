#!/usr/bin/env python3
"""
Ideogram Bulk Image Downloader
===============================
Downloads all your generated images from ideogram.ai using the internal API.

SETUP:
1. Log into ideogram.ai in Chrome
2. Open DevTools (F12) → Network tab → filter by "XHR" or "Fetch"
3. Navigate to your profile/creations page
4. Look at the network requests as images load

You need to extract these values:
- COOKIE: Copy the full Cookie header from any request to ideogram.ai
- AUTH_TOKEN: The Bearer token from the Authorization header
- USER_ID: Your user ID (visible in profile URL or API responses)

Then either:
  a) Set environment variables: IDEO_COOKIE, IDEO_AUTH_TOKEN, IDEO_USER_ID
  b) Create a .env file in this directory
  c) Pass them as command line arguments

USAGE:
  python download.py --cookie "..." --token "..." --user-id "..."
  
  # Or with env vars:
  export IDEO_COOKIE="..."
  export IDEO_AUTH_TOKEN="..." 
  export IDEO_USER_ID="..."
  python download.py
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from http.cookies import SimpleCookie
from urllib.parse import urljoin

try:
    from curl_cffi import requests
    from curl_cffi.requests import Cookies
    USE_CURL_CFFI = True
except ImportError:
    import requests as std_requests
    USE_CURL_CFFI = False
    print("Warning: curl_cffi not installed. Using standard requests.")
    print("If you get blocked, install it: pip install curl_cffi")

BASE_URL = "https://ideogram.ai"
BROWSER_VERSION = "edge101"

HEADERS = {
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
    "DNT": "1",
    "Accept": "application/json",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/json",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
}


def parse_cookie_string(cookie_string):
    """Parse a cookie string into a dict."""
    cookie = SimpleCookie()
    cookie.load(cookie_string)
    return {key: morsel.value for key, morsel in cookie.items()}


class IdeogramDownloader:
    def __init__(self, cookie: str, auth_token: str, user_id: str):
        self.cookie = cookie
        self.auth_token = auth_token
        self.user_id = user_id
        
        headers = HEADERS.copy()
        headers["Authorization"] = f"Bearer {auth_token}"
        
        if USE_CURL_CFFI:
            self.session = requests.Session()
            self.session.headers = headers
            self.session.cookies = Cookies(parse_cookie_string(cookie))
        else:
            self.session = std_requests.Session()
            self.session.headers.update(headers)
            self.session.cookies.update(parse_cookie_string(cookie))
    
    def _get(self, url, **kwargs):
        """Make a GET request with browser impersonation if available."""
        if USE_CURL_CFFI:
            return self.session.get(url, impersonate=BROWSER_VERSION, **kwargs)
        else:
            return self.session.get(url, **kwargs)
    
    def _post(self, url, **kwargs):
        """Make a POST request with browser impersonation if available."""
        if USE_CURL_CFFI:
            return self.session.post(url, impersonate=BROWSER_VERSION, **kwargs)
        else:
            return self.session.post(url, **kwargs)

    def discover_api(self):
        """
        Try known internal API patterns to find the endpoint that lists user images.
        The web app must use one of these to load the creations/profile page.
        """
        print("Probing Ideogram internal API endpoints...")
        
        # These are common patterns used by the Ideogram webapp
        # based on reverse engineering and the IdeoImageCreator project
        endpoints_to_try = [
            # Most likely — POST-based with user_id in body
            ("POST", f"{BASE_URL}/api/images/retrieve_metadata_user_id/{self.user_id}", None),
            ("POST", f"{BASE_URL}/api/images/retrieve_user_creations", {"user_id": self.user_id}),
            
            # GET-based patterns
            ("GET", f"{BASE_URL}/api/images/user/{self.user_id}", None),
            ("GET", f"{BASE_URL}/api/users/{self.user_id}/images", None),
            ("GET", f"{BASE_URL}/api/creations/{self.user_id}", None),
            ("GET", f"{BASE_URL}/api/profile/{self.user_id}", None),
            ("GET", f"{BASE_URL}/api/images/retrieve_user/{self.user_id}", None),
            
            # Pagination-based patterns
            ("POST", f"{BASE_URL}/api/images/search", {"user_id": self.user_id, "page": 0}),
            ("GET", f"{BASE_URL}/api/images/user/{self.user_id}?page=0", None),
            ("GET", f"{BASE_URL}/api/images/user/{self.user_id}?offset=0&limit=50", None),
            
            # NextJS/GraphQL style
            ("POST", f"{BASE_URL}/api/graphql", {"query": "query { userCreations { id url } }"}),
        ]
        
        working_endpoints = []
        
        for method, url, body in endpoints_to_try:
            try:
                if method == "GET":
                    resp = self._get(url)
                else:
                    if body:
                        resp = self._post(url, data=json.dumps(body))
                    else:
                        resp = self._post(url)
                
                status = resp.status_code
                content_type = resp.headers.get("content-type", "")
                
                if status == 200 and "json" in content_type:
                    data = resp.json()
                    print(f"  ✅ {method} {url} → 200 OK (JSON)")
                    # Try to detect if it has image data
                    data_str = json.dumps(data)
                    has_images = any(k in data_str for k in ["response_id", "image_url", "url", "thumbnail", "prompt"])
                    if has_images:
                        print(f"     → Contains image data! Keys: {list(data.keys()) if isinstance(data, dict) else 'array'}")
                        working_endpoints.append((method, url, body, data))
                    else:
                        print(f"     → JSON but no image data detected. Keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
                elif status == 200:
                    print(f"  ⚠️  {method} {url} → 200 but content-type: {content_type}")
                else:
                    print(f"  ❌ {method} {url} → {status}")
                    
            except Exception as e:
                print(f"  ❌ {method} {url} → Error: {e}")
            
            time.sleep(0.3)  # Be gentle
        
        return working_endpoints

    def fetch_all_images(self, endpoint_info=None):
        """
        Fetch all image metadata from the discovered endpoint.
        If no endpoint is provided, runs discovery first.
        """
        if not endpoint_info:
            endpoints = self.discover_api()
            if not endpoints:
                print("\n❌ Could not discover the image listing endpoint automatically.")
                print("\nManual steps to find it:")
                print("1. Open ideogram.ai in Chrome → your profile/creations page")
                print("2. Open DevTools (F12) → Network → XHR filter")
                print("3. Scroll through your images to trigger loading")
                print("4. Find the API request that returns your image data")
                print("5. Copy that URL and the request method/body")
                print("6. Update this script with the correct endpoint")
                return []
            
            method, url, body, sample_data = endpoints[0]
            print(f"\nUsing endpoint: {method} {url}")
        
        # Try to paginate through all results
        all_images = []
        page = 0
        
        while True:
            print(f"Fetching page {page}...")
            
            if body and isinstance(body, dict):
                body["page"] = page
                resp = self._post(url, data=json.dumps(body))
            elif "?" in url:
                paginated_url = f"{url}&page={page}" if "page" not in url else url.replace(f"page={page-1}", f"page={page}")
                resp = self._get(paginated_url)
            else:
                resp = self._get(f"{url}?page={page}")
            
            if resp.status_code != 200:
                print(f"Got status {resp.status_code}, stopping pagination.")
                break
            
            data = resp.json()
            
            # Try to extract image entries from various response shapes
            images = self._extract_images(data)
            
            if not images:
                print(f"No more images found on page {page}.")
                break
            
            all_images.extend(images)
            print(f"  Found {len(images)} images (total: {len(all_images)})")
            
            page += 1
            time.sleep(0.5)
        
        return all_images

    def _extract_images(self, data):
        """Try to extract image entries from various API response formats."""
        if isinstance(data, list):
            return data
        
        if isinstance(data, dict):
            # Try common keys
            for key in ["responses", "images", "results", "data", "creations", "items", "generations"]:
                if key in data and isinstance(data[key], list):
                    return data[key]
            
            # Try nested
            for key in data:
                val = data[key]
                if isinstance(val, list) and len(val) > 0:
                    if isinstance(val[0], dict):
                        return val
        
        return []

    def download_image(self, image_info, output_dir, index):
        """Download a single image."""
        # Try various URL patterns
        url = None
        prompt = "unknown"
        
        if isinstance(image_info, dict):
            # Try to get the direct download URL
            response_id = image_info.get("response_id") or image_info.get("id")
            if response_id:
                url = f"{BASE_URL}/api/images/direct/{response_id}"
            
            # Or a direct URL
            if not url:
                url = image_info.get("url") or image_info.get("image_url") or image_info.get("thumbnail_url")
            
            prompt = image_info.get("prompt", "unknown")
        elif isinstance(image_info, str):
            url = image_info
        
        if not url:
            print(f"  ⚠️ Could not determine URL for image {index}")
            return False
        
        try:
            resp = self._get(url)
            if resp.status_code != 200:
                print(f"  ❌ Failed to download image {index}: HTTP {resp.status_code}")
                return False
            
            # Determine file extension from content-type
            content_type = resp.headers.get("content-type", "image/png")
            ext = "png"
            if "jpeg" in content_type or "jpg" in content_type:
                ext = "jpg"
            elif "webp" in content_type:
                ext = "webp"
            
            # Clean prompt for filename
            safe_prompt = re.sub(r'[^\w\s-]', '', prompt[:60]).strip().replace(' ', '_')
            filename = f"{index:04d}_{safe_prompt}.{ext}"
            filepath = os.path.join(output_dir, filename)
            
            with open(filepath, "wb") as f:
                f.write(resp.content)
            
            size_kb = len(resp.content) / 1024
            print(f"  ✅ {filename} ({size_kb:.0f} KB)")
            return True
            
        except Exception as e:
            print(f"  ❌ Error downloading image {index}: {e}")
            return False

    def download_all(self, output_dir="./ideogram_images"):
        """Main entry point: discover API, list all images, download them all."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        print("=" * 60)
        print("Ideogram Bulk Image Downloader")
        print("=" * 60)
        print(f"User ID: {self.user_id}")
        print(f"Output: {output_dir}")
        print()
        
        # Step 1: Discover API
        images = self.fetch_all_images()
        
        if not images:
            print("\nNo images found to download.")
            return
        
        print(f"\n{'=' * 60}")
        print(f"Found {len(images)} images. Starting download...")
        print(f"{'=' * 60}\n")
        
        # Save metadata
        metadata_file = os.path.join(output_dir, "metadata.json")
        with open(metadata_file, "w") as f:
            json.dump(images, f, indent=2, default=str)
        print(f"Saved metadata to {metadata_file}\n")
        
        # Step 2: Download all images
        success = 0
        failed = 0
        
        for i, img in enumerate(images):
            if self.download_image(img, output_dir, i):
                success += 1
            else:
                failed += 1
            
            # Rate limit
            if (i + 1) % 10 == 0:
                time.sleep(1)
        
        print(f"\n{'=' * 60}")
        print(f"Done! Downloaded {success}/{len(images)} images.")
        if failed:
            print(f"Failed: {failed}")
        print(f"Output directory: {output_dir}")
        print(f"{'=' * 60}")


def load_env():
    """Try to load .env file if it exists."""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")


def main():
    load_env()
    
    parser = argparse.ArgumentParser(
        description="Download all images from your Ideogram account",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--cookie", "-c", help="Cookie header from browser", 
                       default=os.environ.get("IDEO_COOKIE", ""))
    parser.add_argument("--token", "-t", help="Bearer auth token from browser",
                       default=os.environ.get("IDEO_AUTH_TOKEN", ""))
    parser.add_argument("--user-id", "-u", help="Your Ideogram user ID",
                       default=os.environ.get("IDEO_USER_ID", ""))
    parser.add_argument("--output", "-o", help="Output directory",
                       default="./ideogram_images")
    parser.add_argument("--discover-only", action="store_true",
                       help="Only discover API endpoints, don't download")
    
    args = parser.parse_args()
    
    if not all([args.cookie, args.token, args.user_id]):
        print("❌ Missing credentials. You need to provide:")
        print("   --cookie    (or IDEO_COOKIE env var)")
        print("   --token     (or IDEO_AUTH_TOKEN env var)")
        print("   --user-id   (or IDEO_USER_ID env var)")
        print()
        print("HOW TO GET THESE:")
        print("1. Open Chrome → ideogram.ai → log in")
        print("2. Open DevTools (F12) → Network tab → XHR filter")
        print("3. Click on your profile or navigate to your creations")
        print("4. Click on any XHR request to ideogram.ai")
        print("5. In the Headers tab:")
        print("   - Cookie: Copy the full value from 'cookie' request header")
        print("   - Token: Copy the value after 'Bearer ' in the 'authorization' header")
        print("   - User ID: Look in the request URL or response body for your user ID")
        print()
        print("Then create a .env file in this directory:")
        print('   IDEO_COOKIE="your_cookie_here"')
        print('   IDEO_AUTH_TOKEN="your_token_here"')  
        print('   IDEO_USER_ID="your_user_id_here"')
        sys.exit(1)
    
    downloader = IdeogramDownloader(args.cookie, args.token, args.user_id)
    
    if args.discover_only:
        downloader.discover_api()
    else:
        downloader.download_all(args.output)


if __name__ == "__main__":
    main()
