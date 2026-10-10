"""Generate repository-native vector artwork from the real UCI experiment."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / 'assets/real-data.json').read_text())
entry = data['meters'][0]['horizons']['1']
rows = entry['rows']
mae = entry['metrics']['models']['Ridge']['mae_kw']
maximum = max(max(r['actual'],r['prediction']) for r in rows)*1.1
def line(key):
    return ' '.join(f'{714+i*6.3:.1f},{392-r[key]/maximum*155:.1f}' for i,r in enumerate(rows))
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640">
<defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#131f38"/><stop offset=".55" stop-color="#0c1423"/><stop offset="1" stop-color="#132a35"/></linearGradient><radialGradient id="glow"><stop stop-color="#476be2" stop-opacity=".24"/><stop offset="1" stop-color="#476be2" stop-opacity="0"/></radialGradient><linearGradient id="btn"><stop stop-color="#829dff"/><stop offset="1" stop-color="#587cf0"/></linearGradient></defs>
<rect width="1280" height="640" rx="20" fill="url(#bg)"/><rect x=".5" y=".5" width="1279" height="639" rx="20" fill="none" stroke="#324667"/><circle cx="910" cy="240" r="360" fill="url(#glow)"/>
<g font-family="Arial,Helvetica,sans-serif">
<rect x="49" y="45" width="40" height="40" rx="11" fill="url(#btn)"/><path d="M73 52 59 70h10l-5 12 16-21H70z" fill="#f1f6ff"/><text x="104" y="74" fill="#eef3ff" font-size="29" font-weight="700" letter-spacing="-1">GridLedger</text><text x="281" y="72" fill="#879ec1" font-size="11" letter-spacing="2">ENERGY ANALYTICS</text>
<rect x="1105" y="47" width="123" height="30" rx="15" fill="#1c3150" stroke="#37577f"/><circle cx="1124" cy="62" r="3" fill="#4ee2d0"/><text x="1136" y="66" fill="#abc0e6" font-size="10" letter-spacing="1">VERSION 2.0</text>
<text x="51" y="146" fill="#4ee2d0" font-size="10" letter-spacing="3">REAL ELECTRICITY. REPRODUCIBLE RESULTS.</text>
<text x="46" y="222" fill="#f0f4ff" font-size="69" font-weight="700" letter-spacing="-3">Real</text><text x="46" y="295" fill="#93acff" font-size="69" font-weight="700" letter-spacing="-3">demand.</text>
<text x="50" y="339" fill="#9eb1d0" font-size="17">20 UCI clients, three forecast horizons,</text><text x="50" y="365" fill="#9eb1d0" font-size="17">four future windows and verifiable records.</text>
<rect x="50" y="403" width="228" height="49" rx="9" fill="url(#btn)"/><path d="m72 420 11 7-11 7z" fill="#102043"/><text x="96" y="433" fill="#0d1b38" font-size="14" font-weight="700">Open live demo</text><text x="244" y="434" fill="#0d1b38" font-size="20">↗</text><text x="296" y="433" fill="#758eaf" font-size="12">Runs in your browser</text>
<rect x="666" y="137" width="562" height="321" rx="18" fill="#142138" stroke="#344d75"/><circle cx="690" cy="162" r="3" fill="#4ee2d0"/><text x="702" y="166" fill="#9eb3d7" font-size="10" letter-spacing="2">HOURLY DEMAND REPLAY</text><text x="695" y="211" fill="#f0f4ff" font-size="29" font-weight="700">{mae:.2f}<tspan font-size="13" fill="#8ba6cc" font-weight="400"> kW / final-fold MAE</tspan></text><text x="1096" y="204" fill="#6ccfbb" font-size="10">MT_001 / 1h RIDGE</text>
<g stroke="#2a3b55">{''.join(f'<line x1="714" x2="1164" y1="{y}" y2="{y}"/>' for y in [258,302,346,390])}</g><polyline points="{line('actual')}" fill="none" stroke="#91aaff" stroke-width="2" opacity=".65"/><polyline points="{line('prediction')}" fill="none" stroke="#4ee2d0" stroke-width="2.8" stroke-linejoin="round"/>
<text x="714" y="431" fill="#6f87ae" font-size="9">03 NOV</text><text x="917" y="431" fill="#6f87ae" font-size="9">04 NOV</text><text x="1127" y="431" fill="#6f87ae" font-size="9">05 NOV</text><text x="1030" y="162" fill="#829cc5" font-size="9">REAL UCI / PROVIDER CLOCK</text>
<line x1="50" x2="1228" y1="495" y2="495" stroke="#2a3e5c"/>
<g fill="#6c8dff" font-size="12"><text x="51" y="538">01 / FORECAST</text><text x="454" y="538">02 / EXPLORE</text><text x="851" y="538">03 / VERIFY</text></g>
<g fill="#d9e5fa" font-size="19" font-weight="600"><text x="51" y="568">Temporal evaluation</text><text x="454" y="568">Missing input stress</text><text x="851" y="568">Traceable predictions</text></g><g fill="#7892b9" font-size="11"><text x="51" y="591">Four test windows · Five model comparisons</text><text x="454" y="591">Controlled input loss · Frozen models</text><text x="851" y="591">Pinned source · Digests · Local EVM</text></g></g></svg>'''
(ROOT / 'assets/hero.svg').write_text(svg)
(ROOT / 'assets/open-demo.svg').write_text('''<svg xmlns="http://www.w3.org/2000/svg" width="232" height="52" viewBox="0 0 232 52"><rect x="1" y="1" width="230" height="50" rx="9" fill="#6485fa" stroke="#9ab0ff"/><path d="m22 18 12 8-12 8z" fill="#071b38"/><text x="49" y="32" font-family="Arial" font-size="15" font-weight="700" fill="#071b38">Open live demo</text><path d="M198 19h12v12m0-12-14 14" fill="none" stroke="#071b38" stroke-width="2"/></svg>''')
print('Vector brand assets generated from exported predictions.')
