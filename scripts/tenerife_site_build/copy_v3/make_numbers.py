"""numbers.md: все цифры сайта из одной модели + проверка арифметики в текстах.

1. MODEL — исходные величины (PROPOSAL дизайнера, канон, источники sources_v3 §7).
2. Все производные считаются здесь же; токен для поиска = отформатированный результат.
3. Проверки (скрипт падает с кодом 1 при ошибке):
   a) каждое выражение «a × b = c» / «a ÷ b = c» в текстах страниц пересчитывается;
   b) таблицы расходов с «Итого» — сумма строк = итог (€ и %), итог = модели;
   c) каждый токен модели встречается в текстах (кроме помеченных opt=True);
   d) запрещённые остатки: 118 €, 101 €, [уточнить], 27%.
"""
import re,glob,sys,os
from decimal import Decimal, ROUND_HALF_UP
os.chdir(os.path.dirname(os.path.abspath(__file__)))
def hu(x,dec=0):
    """Единое правило округления сайта: ROUND HALF-UP (0,5 → вверх), как в model.json и calc.js."""
    return Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-dec), rounding=ROUND_HALF_UP)
def rint(x): return int(hu(x))
def fmt(x,dec=0):
    if dec==0:
        s=f"{rint(x):,}".replace(',',' ')
    else:
        s=f"{hu(x,dec):,.{dec}f}".replace(',','X').replace('.',',').replace('X',' ')
    return s
import json as _json, os as _os, pathlib as _pl
def _find_inputs():
    env = _os.environ.get("TENERIFE_MODEL_INPUTS")
    if env:
        return _pl.Path(env)
    here = _pl.Path(__file__).resolve()
    for base in (here.parents[1], here.parents[2] if len(here.parents) > 2 else here.parents[1],
                 _pl.Path(_os.environ.get("TENERIFE_BUILD_DIR", str(here.parents[1])))):
        cand = base / "model_inputs.json"
        if cand.is_file():
            return cand
    raise SystemExit("make_numbers: model_inputs.json not found")

_INPUTS_PATH = _find_inputs()
_INPUTS = _json.loads(_INPUTS_PATH.read_text(encoding="utf-8"))
STAGES = [(n, p) for n, p in _INPUTS["stages"]]
MONTHS = int(_INPUTS.get("installment_months", 12))
DISC = float(_INPUTS.get("installment_discount_pct", 0)) / 100.0
RENT=13.5; G=RENT*12; AVG=(1308+1510)/2/20   # 70,45 м²
COMM=200; BAS=120/80
items=[("IBI",300/80),("Взносы сообщества",COMM*12/AVG),("Управление",G*0.10*1.07),("Простой",RENT*0.5),
       ("Страховка",280/80),("Резерв на ремонт",G*0.05),("Сбор за мусор",BAS)]
COST=sum(float(hu(v,2)) for _,v in items); D=rint(G-COST)   # 87
def scen(rent,area,mg,vac,rep):
    g=rent*12; c=300/80+COMM*12/area+g*mg*1.07+rent*vac+280/80+g*rep+BAS; return c,c/g,g-c
mild=scen(13.5,75.5,.08,.5,.04); strict=scen(12,65.4,.12,1,.06)
TOK=[]
def t(name,val,opt=False): TOK.append((name,val,opt))
for n,p in STAGES: t(f"Ступень «{n}», €/м² (PROPOSAL)",fmt(p))
t("Аренда-середина, €/м²/мес","13,5"); t("Аренда × 12, € с метра","162 €")
for n,v in items:
    dec=2 if n in("IBI","Простой") else 1
    t(f"Расходы: {n}, € с м²/год",fmt(v,dec)); t(f"Расходы: {n}, % от 162 €",fmt(v/G*100,1)+"%")
t("Расходы итого, € с м²/год","75,0"); t("Расходы итого, %",fmt(COST/G*100,1)+"%")
t("Дивиденд, € на акцию в год, расчётно, до налога на прибыль компании",f"{D} €",opt=True)
t("Мягкий сценарий, расходы %",fmt(mild[1]*100,1)+"%"); t("Мягкий сценарий, дивиденд",f"около {rint(mild[2])} €")
t("Строгий сценарий, расходы %",fmt(strict[1]*100,1)+"%"); t("Строгий сценарий, дивиденд",f"около {rint(strict[2])} €")
t("Жилая площадь, сумма по типам","1 308–1 510")
# 2026-11-02: в hero — не цена за метр, а минимальная цена юнита (младший тип, середина площади × цена очереди)
SMALL=(48,55); SMALL_MID=rint((SMALL[0]+SMALL[1])/2); QUEUE=STAGES[0][1]
t("Минимальная цена юнита, €",fmt(SMALL_MID*QUEUE))
for m in (48,72,100):
    for n,p in STAGES:
        if m==72 or n in("Очередь","Ввод"): t(f"{m} м² × {fmt(p)}",fmt(m*p))
    t(f"{m} м² × 2 950 ÷ 6",fmt(m*2950*(1-DISC)/6),opt=True); t(f"Разница {m} м² ввод−очередь",fmt(m*(3850-2950)))
    t(f"{m} × {D} (дивиденд в год)",fmt(m*D),opt=True); t(f"{m} × {D} ÷ 12",fmt(m*D/12),opt=True)
t("72 м² × 3 450 ÷ 6",fmt(72*3450*(1-DISC)/6),opt=True)
t("72 м²: очередь→разрешение",fmt(72*(3100-2950)))
for a,b in((48,55),(68,78),(85,100)):
    t(f"{a}–{b} м² × 2 950",f"{fmt(a*2950)}–{fmt(b*2950)}")
    t(f"{a}–{b} × {D} (дивиденд)",f"{fmt(a*D)}–{fmt(b*D)}",opt=True)
for a,b in((48,55),(85,100)):
    t(f"{a}–{b} м² × 3 850",f"{fmt(a*3850)}–{fmt(b*3850)}")
    t(f"{a}–{b} м² × 12–15 € аренды/мес",f"{fmt(a*12)}–{fmt(b*15)}")
t("72 м² × 12–15 € аренды/мес","864–1 080"); t("72 м² × 12–15 € × 12","10 368–12 960")
t("IGIC 7% от 277 200",fmt(277200*.07)); t("AJD 1% от 277 200",fmt(277200*.01))
for n,p in STAGES:
    t(f"Рост до цены ввода от {fmt(p)}",fmt((3850/p-1)*100,1)+"%",opt=(n=="Ввод"))
    t(f"{D} / {fmt(p)}",fmt(D/p*100,1)+"%",opt=True)
t("Оплата сразу полностью: бонус (ОСН 31.10)","бонус 10%"); t("Оплата за полгода: бонус (ОСН 31.10)","бонус 5%"); t("Оплата за год (ОСН 31.10)","без бонуса")
t("Резиденция 1 спальня = акций","48–55 акций"); t("2 спальни = акций","68–78 акций"); t("Большой дом = акций","85–100 акций")
t("Докупка 50→72","22 акци")
t("PVGIS La Quinta, кВт·ч/кВт в год, панели плоско","1 490"); t("Канары среднее, кВт·ч/кВт","1 771") 
t("PVGIS La Quinta, оптимальный наклон 23°","1 578")
# Дом на вводе (КАНОН 3 800–4 600 €/м²) × площадь
HOUSE=(3800,4600)
for a_,b_ in((48,55),(68,78),(85,100)):
    t(f"Дом на вводе {a_}–{b_} м² × 3 800–4 600",f"{fmt(a_*HOUSE[0])}–{fmt(b_*HOUSE[1])}")
t("Дом на вводе 72 м² × 3 800–4 600",f"{fmt(72*HOUSE[0])}–{fmt(72*HOUSE[1])}")
t("Дом на вводе 100 м² × 3 800 (от)",f"от {fmt(100*HOUSE[0])}")
# Вилки месячной аренды (06): площадь × 12–15 € (Santa Úrsula) и × 17 € (Puerto, Fotocasa)
t("Дом 50 м²","50 м²"); t("Дом 95 м²","95 м²")
for m_ in (50,72,95):
    if m_!=72: t(f"{m_} м² × 12–15 €",f"{fmt(m_*12)}–{fmt(m_*15)}")
    t(f"{m_} м² × 17 € (Puerto)",f"около {fmt(m_*17)} €")
t("Пример счёта 120 €/мес × 12 (grupodlt)",fmt(120*12))
t("Расходы итого, € с метра (округл.)","75 € с метра")
t("Докупка: начали с","50 акций")
# Рыночные значения с источником (sources_v3 §4)
t("La Quinta III, цены 4 домов (estatenearme)","420 000–425 000"); t("La Quinta III, € за м² = 420–425 тыс. ÷ 125",f"{fmt(420000/125)}–{fmt(425000/125)}")
t("La Quinta 2, цены (estatenearme)","399 999–425 700"); t("La Quinta 2, € за м² ÷ 110",f"{fmt(399999/110)}–{fmt(425700/110)}")
t("Kelify, районы Santa Úrsula, март 2026, €/м²","10,00–11,67"); t("Kelify, La Quinta 80 м²","975 €"); t("Kelify, La Quinta 60 м²","900 €"); t("Kelify, La Quinta 132 м² (8 oct 2026)","1 500 €")

files=sorted(f for f in glob.glob("[01][0-9]_*.md"))
texts={f:open(f,encoding='utf-8').read() for f in files}
err=[]
# a) арифметика в текстах
N=r'(\d{1,3}(?:\s\d{3})+|\d+(?:,\d+)?)'
expr=re.compile(N+r'\s*(?:м²\s*|акци\w*\s*|€\s*)?([×÷])\s*'+N+r'\s*€?\s*=\s*'+N)
def num(s): return float(s.replace(' ','').replace(',','.'))
nexpr=0
for f,s in texts.items():
    for i,l in enumerate(s.splitlines(),1):
        for m in expr.finditer(l):
            a,op,b,c=num(m.group(1)),m.group(2),num(m.group(3)),num(m.group(4))
            r=a*b if op=='×' else a/b; nexpr+=1
            if abs(r-c)>max(1,abs(c)*0.0005) : err.append(f"{f}:{i}: {m.group(0)} → {r:g}")
# b) таблицы расходов
for f,s in texts.items():
    for blk in re.findall(r'(\| Статья \|.*?\| \*\*Итого\*\*[^\n]*)',s,re.S):
        rows=[r for r in blk.splitlines() if r.startswith('|') and not r.startswith('|---') and 'Статья' not in r]
        eur=pct=0
        for r in rows[:-1]:
            c=[x.strip() for x in r.strip('|').split('|')]; eur+=num(c[1]); pct+=num(c[2].rstrip('%'))
        c=[x.strip('* ') for x in rows[-1].strip('|').split('|')]
        if abs(eur-num(c[1]))>0.051 or abs(pct-num(c[2].rstrip('%')))>0.051: err.append(f"{f}: таблица расходов: сумма {eur:.2f}/{pct:.1f}% ≠ итог {c[1]}/{c[2]}")
        if abs(num(c[1])-float(hu(COST,1)))>0.051: err.append(f"{f}: итог таблицы {c[1]} ≠ модель {COST:.1f}")
# d) остатки
for f,s in texts.items():
    for bad in (r'(?<![\d,])118(?![\d,])',r'10,5–15,7',r'(?<![\d ])285 000',r'сдача конец 2026',r'I–II квартал 2027',r'сегодня продаются',r'сегодня предлагают',r'La Laguna',r'одинаковом наклоне',r'на день покупки',r'Архив отчётов',r'норма квартала',r'получают отчёт',r'получаете отчёт',r'[Лл]ист\w* ожидани',r'(?<![\d,])101 €',r'\[уточнить\]',r'(?<![\d,])27 ?%',r'(?<![\d,])147 500',r'через 3 мес',r'через три месяца',r'три месяца между',r'Покупка акций через',r'Где именно\?',r'надбавк'):
        for m in re.finditer(bad,s): err.append(f"{f}: запрещённый остаток «{m.group(0)}»")
out=["# numbers.md — все цифры сайта из одной модели","",
f"Сгенерировано make_numbers.py. Модель 02.11.2026: цены — пределами, дивиденд публикуется только в процентах (2,5–3,5 % годовых до налога на прибыль компании), оплата — сразу со скидкой на цену входа или шестью равными платежами со скидкой 5 % от всей цены; твёрдые суммы дивиденда на сайте не показываем (основатель 02.11). Дивиденд {D} € на акцию в год остаётся внутренним расчётом: 13,5 × 12 = 162 € минус {fmt(COST,1)} € ({fmt(COST/G*100,1)} %) расходов по семи статьям.",
f"Проверено выражений «a × b = c» / «a ÷ b = c» в текстах: {nexpr}.",""]
for name,tok,opt in TOK:
    pat=re.compile(r'(?<![\d,–])'+re.escape(tok)+(r'(?![\d,]\d)' if tok[-1].isdigit() else ''))
    hits=[]
    for f in files:
        for i,l in enumerate(texts[f].splitlines(),1):
            m=pat.search(l)
            if m:
                ph=l.strip(); m=pat.search(ph); a=max(0,m.start()-70); b=min(len(ph),m.end()+70)
                hits.append(f"| {f}:{i} | …{ph[a:b].replace('|','¦')}… |")
    if not hits and not opt: err.append(f"токен модели не найден в текстах: {tok} ({name})")
    out.append(f"## {tok} — {name}  ({len(hits)} вхожд.)\n"); out.append("| Файл:строка | Фраза |\n|---|---|")
    out+=hits or ["| — | не встречается |"]; out.append("")
out.insert(4,"**Проверка: "+("ОК, ошибок нет" if not err else f"{len(err)} ошибок")+"**\n"+"\n".join("- "+e for e in err)+"\n")
open("numbers.md","w",encoding='utf-8').write("\n".join(out))
print(f"D={D} COST={COST:.2f} ({COST/G*100:.1f}%) mild={mild[2]:.1f} ({mild[1]*100:.1f}%) strict={strict[2]:.1f} ({strict[1]*100:.1f}%) exprs={nexpr} tokens={len(TOK)}")
for e in err: print("ERR",e)
sys.exit(1 if err else 0)
