import os
import re
import sys

from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://portal.infobip.com"
CAMPAIGNS_API_TEMPLATE = f"{BASE_URL}/api/public/flows/1/cup/campaigns/{{campaign_id}}"
UPLOADED_HTML_API_TEMPLATE = (
    f"{BASE_URL}/api/public/email/message/get-uploaded-html/{{uploaded_content_id}}?htmlOnly=true"
)
REQUIRED_COOKIES = ("IbAuthCookie", "IbTokenCookie", "_csrf")
DEFAULT_CAMPAIGN_REFS = ["200000035923631", "200000035923988"]

def build_cookie_header(playwright_cookies):
    by_name = {}

    for cookie in playwright_cookies:
        domain = cookie.get("domain", "").lstrip(".")
        if domain.endswith("infobip.com"):
            by_name[cookie["name"]] = cookie["value"]

    cookie_parts = [f"{name}={value}" for name, value in by_name.items()]

    return "; ".join(cookie_parts)

def normalize_campaign_id(campaign_ref):
    campaign_ref = str(campaign_ref).strip()
    if "/" in campaign_ref:
        campaign_ref = campaign_ref.rstrip("/").split("/")[-1]
    return campaign_ref

def build_api_headers(cookie_header, csrf_token):
    return {
        "Cookie": cookie_header,
        "X-CSRF-Token": csrf_token,
        "Referer": f"{BASE_URL}/",
        "Accept": "application/json, text/plain, */*",
    }

def extract_uploaded_content_ids(campaign_payload):
    ids = []
    flow_data = campaign_payload.get("flowData", {})
    flow_elements = flow_data.get("flowElements", [])

    for element in flow_elements:
        if element.get("type") != "SEND_ACTION":
            continue
        if element.get("label") != "Email":
            continue

        service_data = (
            element.get("action", {})
            .get("serviceMessagingData", {})
            .get("serviceData", {})
        )
        uploaded_content_id = service_data.get("uploadedContentId")
        if uploaded_content_id:
            ids.append(uploaded_content_id)

    return list(dict.fromkeys(ids))

def normalize_html(html_content):
    return html_content.replace("\\n", "").replace("\\t", "").replace('\\"', '"')

def sanitize_filename(name):
    safe_name = re.sub(r'[<>:"/\\|?*]+', "_", name).strip().rstrip(".")
    return safe_name or "campaign"

def save_html_file(campaign_name, html_content):
    filename = f"{sanitize_filename(campaign_name)}.html"
    with open(filename, "w", encoding="utf-8") as file:
        file.write(html_content)
    return filename

def get_cookie_value(playwright_cookies, cookie_name):
    for cookie in playwright_cookies:
        if cookie.get("name") == cookie_name:
            return cookie.get("value")
    return None

def wait_for_required_cookies(context, page):
    attempts = 20
    for _ in range(attempts):
        cookies = context.cookies()
        cookie_names = {cookie.get("name") for cookie in cookies}
        if all(name in cookie_names for name in REQUIRED_COOKIES):
            return cookies
        page.wait_for_timeout(500)

    return context.cookies()

def get_campaign_refs():
    if len(sys.argv) > 1:
        return sys.argv[1:]
    return DEFAULT_CAMPAIGN_REFS

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    page.goto(f"{BASE_URL}/login")

    try:
        page.click("button:has-text('Allow all cookies')", timeout=5000)
    except Exception:
        pass

    page.fill("input[name='username']", os.getenv("INFOBIP_USERNAME"))
    page.click("button:has-text('CONTINUE')")
    page.fill("input[name='password']", os.getenv("INFOBIP_PASSWORD"))
    page.click("button:has-text('LOG IN')")

    page.wait_for_load_state("networkidle")

    cookies = wait_for_required_cookies(context, page)
    cookie_header = build_cookie_header(cookies)
    csrf_token = get_cookie_value(cookies, "_csrf")
    cookie_names = sorted({cookie.get("name") for cookie in cookies if cookie.get("name")})
    print("Cookies capturados:", ", ".join(cookie_names))

    missing = [name for name in REQUIRED_COOKIES if not get_cookie_value(cookies, name)]
    if missing:
        raise RuntimeError(f"Cookies obrigatorios ausentes: {', '.join(missing)}")

    if not cookie_header:
        raise RuntimeError("Nenhum cookie encontrado para dominios infobip.com.")

    api_headers = build_api_headers(cookie_header, csrf_token)

    for campaign_ref in get_campaign_refs():
        campaign_id = normalize_campaign_id(campaign_ref)
        campaign_url = CAMPAIGNS_API_TEMPLATE.format(campaign_id=campaign_id)

        campaign_response = context.request.get(campaign_url, headers=api_headers)
        print(f"Campaign {campaign_id} status: {campaign_response.status}")
        if campaign_response.status != 200:
            print(f"Falha ao buscar campanha {campaign_id}: {campaign_response.text()}")
            continue

        campaign_payload = campaign_response.json()
        campaign_name = campaign_payload.get("name", f"campaign_{campaign_id}")
        uploaded_ids = extract_uploaded_content_ids(campaign_payload)

        if not uploaded_ids:
            print(f"Campanha {campaign_id} sem SEND_ACTION/Email com uploadedContentId.")
            continue

        for uploaded_id in uploaded_ids:
            html_url = UPLOADED_HTML_API_TEMPLATE.format(uploaded_content_id=uploaded_id)
            html_response = context.request.get(html_url, headers=api_headers)
            print(f"Uploaded HTML {uploaded_id} status: {html_response.status}")
            if html_response.status != 200:
                print(
                    f"Falha ao buscar uploaded HTML {uploaded_id} da campanha {campaign_id}: "
                    f"{html_response.text()}"
                )
                continue

            html_payload = html_response.json()
            html_content = normalize_html(html_payload.get("html", ""))
            output_file = save_html_file(campaign_name, html_content)
            print(f"Arquivo salvo: {output_file}")

    browser.close()
