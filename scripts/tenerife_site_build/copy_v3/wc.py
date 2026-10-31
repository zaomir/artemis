"""Проверка страниц RU v3.

Слова (метод раунда 4): считаются только буквенно-цифровые токены видимого текста.
Не считаются: блок META и любые HTML-комментарии, маркеры [КАДР Fxx], строка кнопки
и подпись под ней, а также знаки «—», «€», «·», «=», «×», «÷», «→», «|», «#», «*».
Число с разрядами через пробел («212 400», «1 308») — одно слово; дефис, апостроф
и десятичная запятая внутри токена не разбивают его («компании-застройщика», «13,5»).
Минимум: 700 слов на страницу, 500 — калькулятор (05); подвал (14), юридические страницы (15, 16) и общая форма (17) без минимума.
"""
import re,sys,glob,os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
NUM=r'\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:,\d+)?'
WORD=re.compile(NUM+r'|[^\W_]+(?:[-’\'.,][^\W_]+)*')
def visible(s):
    s=re.sub(r'<!--.*?-->','',s,flags=re.S)
    s=re.sub(r'\[КАДР F\d\d\]','',s)
    s=re.sub(r'^\*\*Кнопка:.*\n.*$','',s,flags=re.M)
    return s
# без минимума слов, кнопки, кадров и meta description: подвал (14) и юридические страницы (15 Impressum, 16 конфиденциальность), общая форма (17)
NOMIN={'14','15','16','17'}
bad=0
for f in sorted(glob.glob('[0-9][0-9]_*.md')):
    s=open(f,encoding='utf-8').read()
    meta=re.search(r'<!-- META(.*?)-->',s,re.S)
    body=re.sub(r'<!--.*?-->','',s,flags=re.S)
    frames=re.findall(r'\[КАДР (F\d\d)\]',body)
    words=len(WORD.findall(visible(s)))
    h1=re.search(r'^# (.+)$',body,re.M); h1=h1.group(1) if h1 else ''
    m={}
    if meta:
        for k in ['Meta title','Meta description','OG title']:
            mm=re.search(k+r': (.+)',meta.group(1)); m[k]=len(mm.group(1).strip()) if mm else None
    cta=len(re.findall(r'\*\*Кнопка:',body))
    need=0 if f[:2] in NOMIN else (500 if f.startswith('05') else 700)
    flags=[]
    if words<need: flags.append(f'WORDS<{need}')
    if f[:2] not in NOMIN:
        if len(h1)>70: flags.append('H1>70')
        if (m.get('Meta title') or 99)>60: flags.append('TITLE>60')
        d=m.get('Meta description') or 0
        if not 140<=d<=160: flags.append('DESC')
        if cta!=1: flags.append('CTA')
        if len(frames)!=6 or len(set(frames))!=6: flags.append('FRAMES')
    bad+=bool(flags)
    print(f"{f}: words={words} frames={len(frames)}({len(set(frames))} uniq) hero={frames[0] if frames else '-'} H1len={len(h1)} title={m.get('Meta title')} desc={m.get('Meta description')} og={m.get('OG title')} cta={cta} {' '.join(flags) or 'OK'}")
sys.exit(1 if bad else 0)
