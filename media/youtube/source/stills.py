import sys, json, asyncio
from playwright.async_api import async_playwright
from script import BEATS
# job list: (name, scene, step, caption, prog)
async def main(jobs):
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await b.new_page(viewport={'width':1920,'height':1080})
        await pg.goto('file:///home/claude/vid/scenes.html'); await pg.wait_for_timeout(500)
        await pg.evaluate('document.fonts.ready')
        for name,sid,step,cap,prog in jobs:
            await pg.evaluate('([a,b,c,d])=>show(a,b,c,d)',[sid,step,cap,prog])
            await pg.screenshot(path=name,type='jpeg',quality=92)
        await b.close()
if __name__=='__main__':
    jobs=json.load(open(sys.argv[1])); asyncio.run(main(jobs))
