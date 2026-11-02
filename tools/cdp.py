#!/usr/bin/env python3
"""Tiny Chrome-DevTools-Protocol client for Steam's CEF (port 8080): eval JS / screenshot a tab.

  cdp.py list
  cdp.py eval  <title-substring> '<js expression>'
  cdp.py shot  <title-substring> out.png
  cdp.py tall  <title-substring> out.png height   (temporarily enlarge the viewport so a long panel fits)
  cdp.py clicktext <title-substring> 'visible text'
  cdp.py click <title-substring> x y        (CSS pixels)
  cdp.py wheel <title-substring> x y dy     (scroll; positive = down)
"""
import asyncio, base64, json, sys, urllib.request

def targets():
    return json.load(urllib.request.urlopen("http://localhost:8080/json"))

def pick(sub):
    for t in targets():
        if sub in t["title"]:
            return t
    sys.exit(f"no tab with '{sub}'")

async def call(ws_url, method, params=None):
    import websockets
    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                return m

def mouse(tab, typ, x, y, **kw):
    return asyncio.run(call(pick(tab)["webSocketDebuggerUrl"], "Input.dispatchMouseEvent",
                            dict(type=typ, x=x, y=y, **kw)))

def main():
    cmd = sys.argv[1]
    if cmd == "list":
        for t in targets():
            print(t["title"], "|", t["url"][:80])
    elif cmd == "eval":
        r = asyncio.run(call(pick(sys.argv[2])["webSocketDebuggerUrl"], "Runtime.evaluate",
                             {"expression": sys.argv[3], "returnByValue": True, "awaitPromise": True}))
        print(json.dumps(r.get("result", r), indent=1, ensure_ascii=False))
    elif cmd == "shot":
        r = asyncio.run(call(pick(sys.argv[2])["webSocketDebuggerUrl"], "Page.captureScreenshot", {"format": "png"}))
        open(sys.argv[3], "wb").write(base64.b64decode(r["result"]["data"]))
        print("saved", sys.argv[3])
    elif cmd == "tall":
        async def run():
            import websockets
            async with websockets.connect(pick(sys.argv[2])["webSocketDebuggerUrl"], max_size=128 * 1024 * 1024) as ws:
                async def rpc(i, m, p=None):
                    await ws.send(json.dumps({"id": i, "method": m, "params": p or {}}))
                    while True:
                        r = json.loads(await ws.recv())
                        if r.get("id") == i:
                            return r
                await rpc(1, "Emulation.setDeviceMetricsOverride",
                          {"width": 855, "height": int(sys.argv[4]), "deviceScaleFactor": 1, "mobile": False})
                await asyncio.sleep(1.5)
                r = await rpc(2, "Page.captureScreenshot", {"format": "png"})
                await rpc(3, "Emulation.clearDeviceMetricsOverride")
                open(sys.argv[3], "wb").write(base64.b64decode(r["result"]["data"]))
        asyncio.run(run())
        print("saved", sys.argv[3])
    elif cmd == "clicktext":
        tab, text = sys.argv[2], sys.argv[3]
        js = ("(()=>{const els=[...document.querySelectorAll('div,span,button')].filter(e=>e.children.length==0&&"
              "e.innerText&&e.innerText.trim()===%s);const r=els[0]&&els[0].getBoundingClientRect();"
              "return r?[r.x+r.width/2,r.y+r.height/2]:null})()") % json.dumps(text)
        r = asyncio.run(call(pick(tab)["webSocketDebuggerUrl"], "Runtime.evaluate", {"expression": js, "returnByValue": True}))
        pos = r["result"]["result"].get("value")
        if not pos:
            sys.exit(f"text '{text}' not found")
        mouse(tab, "mouseMoved", *pos)
        mouse(tab, "mousePressed", *pos, button="left", clickCount=1)
        mouse(tab, "mouseReleased", *pos, button="left", clickCount=1)
    elif cmd == "click":
        tab, x, y = sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
        mouse(tab, "mouseMoved", x, y)
        mouse(tab, "mousePressed", x, y, button="left", clickCount=1)
        mouse(tab, "mouseReleased", x, y, button="left", clickCount=1)
    elif cmd == "wheel":
        tab, x, y, dy = sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
        mouse(tab, "mouseWheel", x, y, deltaX=0, deltaY=dy)

main()
