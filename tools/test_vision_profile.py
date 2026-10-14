#!/usr/bin/env python3
"""Live screenshot-reading and changed-image regression check; switches the router model."""
import argparse
import base64
import json
from pathlib import Path
import time
import urllib.request
from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8096')
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--filler-tokens', type=int, default=0, help='append repeated filler words to exercise cache growth with images')
    args = parser.parse_args()
    if not 0 <= args.filler_tokens <= 200000:
        parser.error('--filler-tokens must be between 0 and 200000')
    args.output.mkdir(parents=True, exist_ok=True)
    font_path = Path('/usr/share/fonts/TTF/DejaVuSansMono.ttf')
    font = ImageFont.truetype(str(font_path), 24) if font_path.is_file() else ImageFont.load_default(size=24)
    cases = [{'file': 'src/game.js', 'line': 42, 'error_code': 'ERR-7314', 'message': 'snake is not defined'},
             {'file': 'src/router.py', 'line': 87, 'error_code': 'ERR-2059', 'message': 'worker is not ready'}]
    results = []
    for index, expected in enumerate(cases):
        screenshot = Image.new('RGB', (640, 320), '#f8fafc')
        draw = ImageDraw.Draw(screenshot)
        text = ('BUILD FAILED\n\nFile: '+expected['file']+'\nLine: '+str(expected['line'])+
                '\nError code: '+expected['error_code']+'\n'+expected['message'])
        draw.multiline_text((24, 24), text, fill='#111827', font=font, spacing=8)
        path = args.output/f'screenshot-{index+1}.png'
        screenshot.save(path)
        uri = 'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()
        body = {'model': args.model, 'temperature': 0, 'reasoning_effort': 'none', 'max_tokens': 512,
                'messages': [{'role': 'user', 'content': [
                    {'type': 'text', 'text': 'Read this build-error screenshot. Return only JSON with keys file, line (integer), error_code, message. Copy the visible values exactly.' + (' Ignore filler words:'+ ' alpha'*args.filler_tokens if args.filler_tokens else '')},
                    {'type': 'image_url', 'image_url': {'url': uri}}]}]}
        started = time.monotonic()
        request = urllib.request.Request(args.base_url+'/v1/chat/completions',
                                        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=600) as response:
            reply = json.load(response)
        (args.output/f'response-{index+1}.json').write_text(json.dumps(reply, indent=2)+'\n')
        content = reply['choices'][0]['message'].get('content') or ''
        try:
            actual = json.loads(content.strip().removeprefix('```json').removesuffix('```').strip())
        except ValueError:
            actual = None
        results.append({'expected': expected, 'actual': actual, 'exact': actual == expected,
                        'elapsed_seconds': round(time.monotonic()-started, 2),
                        'usage': reply.get('usage'), 'timings': reply.get('timings')})
        (args.output/'report.json').write_text(json.dumps({'model': args.model, 'cases': results}, indent=2)+'\n')
        print(json.dumps(results[-1]), flush=True)
    if not all(case['exact'] for case in results):
        raise SystemExit('Screenshot reading did not match the fixture; inspect responses before claiming support')


if __name__ == '__main__':
    main()
