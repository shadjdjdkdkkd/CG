"""Two-party Agora video call E2E with NEW credentials."""
import asyncio, os
from playwright.async_api import async_playwright

BASE = "https://glow-celesta-v.preview.emergentagent.com"
URL = f"{BASE}/consult-room/TESTVID001"

async def setup_ctx(browser, token_key, token_val):
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        permissions=["camera", "microphone"],
    )
    await ctx.grant_permissions(["camera", "microphone"], origin=BASE)
    page = await ctx.new_page()
    logs = []
    page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
    await page.goto(BASE)
    await page.evaluate(f"localStorage.setItem('{token_key}', '{token_val}')")
    await page.goto(URL)
    return ctx, page, logs

async def wait_live(page, label, timeout=45000):
    try:
        await page.wait_for_selector("[data-testid='join-call']", timeout=15000)
    except Exception as e:
        html_snippet = await page.evaluate("() => document.body.innerText.slice(0,500)")
        print(f"{label}: join-call not found. body={html_snippet}")
        raise
    await page.locator("[data-testid='join-call']").first.click()
    await page.wait_for_timeout(1500)
    joined_dbg = await page.evaluate("() => !!document.querySelector('[data-testid=\"agora-call\"], [data-testid=\"zoom-active\"], [data-testid=\"jitsi-frame\"]')")
    print(f"{label}: clicked join-call joined_dbg={joined_dbg}")
    try:
        await page.wait_for_selector("[data-testid='agora-call']", timeout=timeout)
    except Exception as e:
        html_snippet = await page.evaluate("() => document.body.innerText.slice(0,500)")
        print(f"{label}: agora-call not found. body={html_snippet}")
        raise

async def check_remote(page, label):
    # poll for remote video playing
    for i in range(40):
        info = await page.evaluate("""() => {
          const r = document.querySelector('[data-testid="agora-remote"]');
          if (!r) return {found:false};
          const v = r.querySelector('video');
          if (!v) return {found:true, video:false};
          return {found:true, video:true, rs: v.readyState, w: v.videoWidth, h: v.videoHeight, paused: v.paused};
        }""")
        if info.get("video") and info.get("rs", 0) >= 2 and info.get("w", 0) > 0:
            print(f"{label} remote video OK: {info}")
            return True
        await asyncio.sleep(1)
    print(f"{label} remote video FAILED last_info={info}")
    return False

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        d_ctx, d_page, d_logs = await setup_ctx(browser, "mp_doctor_token", "testdoctorcalltoken")
        await wait_live(d_page, "DOCTOR")
        c_ctx, c_page, c_logs = await setup_ctx(browser, "cg_auth_token", "testcustomercalltoken")
        await wait_live(c_page, "CUSTOMER")

        d_ok = await check_remote(d_page, "DOCTOR")
        c_ok = await check_remote(c_page, "CUSTOMER")

        # error log scan
        def scan(logs, label):
            bad = [l for l in logs if "CAN_NOT_GET_GATEWAY_SERVER" in l or "invalid vendor key" in l.lower()]
            print(f"{label} bad_logs={bad}")
            return len(bad) == 0

        d_clean = scan(d_logs, "DOCTOR")
        c_clean = scan(c_logs, "CUSTOMER")

        print(f"BOTH_LIVE: d={d_ok} c={c_ok} clean_d={d_clean} clean_c={c_clean}")

        # End call → doctor
        if d_ok and c_ok:
            await d_page.locator("[data-testid='end-call']").first.click()
            try:
                await d_page.wait_for_selector("[data-testid='call-ended']", timeout=8000)
                print("DOCTOR: call-ended visible")
            except Exception as e:
                print(f"call-ended NOT shown: {e}")
            await asyncio.sleep(3)
            # customer should see remote gone
            c_remote = await c_page.evaluate("""() => {
              const r = document.querySelector('[data-testid="agora-remote"]');
              return r ? r.querySelectorAll('video').length : -1;
            }""")
            print(f"CUSTOMER remote_videos_after_end={c_remote}")

            # Rejoin
            try:
                await d_page.wait_for_selector("[data-testid='rejoin-call']", timeout=5000)
                await d_page.locator("[data-testid='rejoin-call']").first.click()
                print("DOCTOR: rejoin clicked")
                await d_page.wait_for_selector("[data-testid='agora-call']", timeout=15000)
                d2 = await check_remote(d_page, "DOCTOR-REJOIN")
                c2 = await check_remote(c_page, "CUSTOMER-REJOIN")
                print(f"REJOIN_LIVE: d={d2} c={c2}")
            except Exception as e:
                print(f"rejoin failed: {e}")

        # dump last 30 lines of each log for inspection
        print("\n--- DOCTOR LOG TAIL ---")
        for l in d_logs[-25:]: print(l)
        print("\n--- CUSTOMER LOG TAIL ---")
        for l in c_logs[-25:]: print(l)

        await browser.close()

asyncio.run(main())
